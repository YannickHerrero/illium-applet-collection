use crate::model::{self, Process, Raw, Volume};
use std::{mem::size_of, path::Path};
use windows::{
    Win32::{
        Foundation::{CloseHandle, FILETIME, HANDLE},
        NetworkManagement::{
            IpHelper::{FreeMibTable, GetIfTable2, MIB_IF_TABLE2},
            Ndis::IfOperStatusUp,
        },
        Storage::FileSystem::{
            GetDiskFreeSpaceExW, GetDriveTypeW, MOVEFILE_REPLACE_EXISTING, MoveFileExW,
        },
        System::{Diagnostics::ToolHelp::*, ProcessStatus::*, SystemInformation::*, Threading::*},
    },
    core::{PCWSTR, PWSTR},
};
fn ticks(t: FILETIME) -> u64 {
    (u64::from(t.dwHighDateTime) << 32) | u64::from(t.dwLowDateTime)
}
fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(Some(0)).collect()
}
fn text(s: &[u16]) -> String {
    String::from_utf16_lossy(&s[..s.iter().position(|c| *c == 0).unwrap_or(s.len())])
}
struct Handle(HANDLE);
impl Drop for Handle {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseHandle(self.0);
        }
    }
}
pub fn now() -> u64 {
    unsafe { GetTickCount64() }
}
pub fn cpus() -> u32 {
    unsafe { GetActiveProcessorCount(0xffff).max(1) }
}
pub fn diagnose() -> serde_json::Value {
    let timed = |f: &dyn Fn()| {
        let at = std::time::Instant::now();
        f();
        at.elapsed().as_micros() as u64
    };
    serde_json::json!({
        "basic_us":timed(&|| {sample(false);}),
        "network_us":timed(&|| {network();}),
        "disk_us":timed(&|| {disk();}),
        "processes_us":timed(&|| {let _=processes();}),
        "volumes_us":timed(&|| {volumes();}),
    })
}
pub fn sample(detail: bool) -> Raw {
    let mut raw = Raw {
        at: now(),
        ..Default::default()
    };
    unsafe {
        let (mut idle, mut kernel, mut user) = (
            FILETIME::default(),
            FILETIME::default(),
            FILETIME::default(),
        );
        // GetSystemTimes is group-local on >64-processor systems. Do not claim a global value there.
        if cpus() <= 64
            && GetSystemTimes(Some(&mut idle), Some(&mut kernel), Some(&mut user)).is_ok()
        {
            raw.cpu = Some((ticks(kernel) + ticks(user), ticks(idle)));
        }
        let mut memory = MEMORYSTATUSEX {
            dwLength: size_of::<MEMORYSTATUSEX>() as u32,
            ..Default::default()
        };
        if GlobalMemoryStatusEx(&mut memory).is_ok() {
            raw.memory = Some((memory.ullTotalPhys, memory.ullAvailPhys));
        }
    }
    if detail {
        raw.network = network();
        raw.disk = disk();
        raw.io_at = now();
    }
    raw
}
fn network() -> Option<(String, String, u64, u64)> {
    unsafe {
        let mut table: *mut MIB_IF_TABLE2 = std::ptr::null_mut();
        if GetIfTable2(&mut table).is_err() {
            return None;
        }
        let rows =
            std::slice::from_raw_parts((*table).Table.as_ptr(), (*table).NumEntries as usize);
        // Only real, up Ethernet/Wi-Fi adapters: never add a VPN or WSL virtual adapter a second time.
        let mut rows: Vec<_> = rows
            .iter()
            .filter(|r| {
                r.OperStatus == IfOperStatusUp
                    && [6, 71].contains(&r.Type)
                    && r.InterfaceAndOperStatusFlags._bitfield & 1 != 0
            })
            .collect();
        rows.sort_by_key(|r| r.InterfaceIndex);
        let selected = std::env::var("ILLIUM_APPLET_INTERFACE").unwrap_or_default();
        let row = if selected.is_empty() {
            rows.first().copied()
        } else {
            rows.into_iter().find(|r| text(&r.Alias) == selected)
        };
        let result = row.map(|r| {
            (
                format!("{:?}", r.InterfaceGuid),
                text(&r.Alias),
                r.InOctets,
                r.OutOctets,
            )
        });
        FreeMibTable(table.cast());
        result
    }
}
fn disk() -> Option<(u32, u64, u64)> {
    use windows::Win32::{
        Storage::FileSystem::*,
        System::{IO::DeviceIoControl, Ioctl::*},
    };
    let number = std::env::var("ILLIUM_APPLET_DISK")
        .unwrap_or_else(|_| "0".into())
        .parse::<u32>()
        .ok()
        .filter(|n| *n <= 1023)?;
    let path = wide(&format!("\\\\.\\PhysicalDrive{number}"));
    unsafe {
        let handle = Handle(
            CreateFileW(
                PCWSTR(path.as_ptr()),
                0,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            .ok()?,
        );
        let mut perf = DISK_PERFORMANCE::default();
        let mut returned = 0;
        DeviceIoControl(
            handle.0,
            IOCTL_DISK_PERFORMANCE,
            None,
            0,
            Some((&mut perf as *mut DISK_PERFORMANCE).cast()),
            size_of::<DISK_PERFORMANCE>() as u32,
            Some(&mut returned),
            None,
        )
        .ok()?;
        if returned < size_of::<DISK_PERFORMANCE>() as u32 {
            return None;
        }
        Some((
            number,
            u64::try_from(perf.BytesRead).ok()?,
            u64::try_from(perf.BytesWritten).ok()?,
        ))
    }
}
pub fn volumes() -> Vec<Volume> {
    let mut out = Vec::new();
    for letter in 'A'..='Z' {
        let name = format!("{letter}:\\");
        let path = wide(&name);
        unsafe {
            if GetDriveTypeW(PCWSTR(path.as_ptr())) != 3 {
                continue;
            } // fixed local volumes only
            let (mut total, mut free) = (0, 0);
            if GetDiskFreeSpaceExW(
                PCWSTR(path.as_ptr()),
                None,
                Some(&mut total),
                Some(&mut free),
            )
            .is_ok()
                && total > 0
            {
                out.push(Volume {
                    name: format!("{letter}:"),
                    detail: format!(
                        "{} free / {}",
                        model::bytes(Some(free as f64)),
                        model::bytes(Some(total as f64))
                    ),
                    used: (total.saturating_sub(free)) as f64 * 100.0 / total as f64,
                });
            }
        }
    }
    out
}
fn times(handle: HANDLE) -> Option<(u64, u64)> {
    let mut times = [FILETIME::default(); 4];
    unsafe {
        GetProcessTimes(
            handle,
            &mut times[0],
            &mut times[1],
            &mut times[2],
            &mut times[3],
        )
    }
    .ok()?;
    Some((ticks(times[0]), ticks(times[2]) + ticks(times[3])))
}
fn process_name(handle: HANDLE) -> Option<String> {
    let mut buffer = vec![0u16; 32768];
    let mut len = buffer.len() as u32;
    unsafe {
        QueryFullProcessImageNameW(
            handle,
            PROCESS_NAME_WIN32,
            PWSTR(buffer.as_mut_ptr()),
            &mut len,
        )
    }
    .ok()?;
    let path = String::from_utf16_lossy(&buffer[..len as usize]);
    let name = path.rsplit('\\').next()?;
    if name.is_empty() {
        None
    } else {
        Some(name.to_owned())
    }
}
fn safe(handle: HANDLE, pid: u32, name: &str) -> bool {
    if pid <= 4 || model::protected(name) || pid == std::process::id() {
        return false;
    }
    let mut critical = windows::core::BOOL::default();
    unsafe { IsProcessCritical(handle, &mut critical).is_ok() && !critical.as_bool() }
}
pub fn processes() -> Result<Vec<Process>, String> {
    unsafe {
        let snapshot = Handle(
            CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
                .map_err(|_| "Process enumeration unavailable")?,
        );
        let mut entry = PROCESSENTRY32W {
            dwSize: size_of::<PROCESSENTRY32W>() as u32,
            ..Default::default()
        };
        Process32FirstW(snapshot.0, &mut entry).map_err(|_| "Process enumeration unavailable")?;
        let mut out = Vec::new();
        loop {
            let pid = entry.th32ProcessID;
            if pid != 0 && pid != std::process::id() {
                let name = text(&entry.szExeFile);
                let mut p = Process {
                    pid,
                    name,
                    ..Default::default()
                };
                let handle = OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ,
                    false,
                    pid,
                )
                .or_else(|_| OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid));
                if let Ok(handle) = handle {
                    let handle = Handle(handle);
                    if let Some((born, ticks)) = times(handle.0) {
                        p.born = born;
                        p.ticks = Some(ticks);
                    }
                    let mut mem = PROCESS_MEMORY_COUNTERS {
                        cb: size_of::<PROCESS_MEMORY_COUNTERS>() as u32,
                        ..Default::default()
                    };
                    if K32GetProcessMemoryInfo(
                        handle.0,
                        &mut mem,
                        size_of::<PROCESS_MEMORY_COUNTERS>() as u32,
                    )
                    .as_bool()
                    {
                        p.memory = Some(mem.WorkingSetSize as u64);
                    }
                    // Toolhelp's PID could have been reused before OpenProcess.
                    // Bind the displayed name and creation time to the same handle.
                    if let Some(name) = process_name(handle.0) {
                        p.name = name;
                        p.safe = p.born > 0 && safe(handle.0, pid, &p.name);
                    }
                }
                out.push(p);
            }
            if out.len() >= 4096 || Process32NextW(snapshot.0, &mut entry).is_err() {
                break;
            }
        }
        Ok(out)
    }
}
/// Open once, verify identity and critical status, then terminate that SAME handle.
/// No shell, no elevation and no PID-only fallback.
pub fn terminate(key: &str) -> Result<String, String> {
    let (pid, born) = model::identity(key)?;
    unsafe {
        let handle = Handle(
            OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE,
                false,
                pid,
            )
            .map_err(|_| "Cannot end this process: access denied or process already exited")?,
        );
        if times(handle.0).map(|t| t.0) != Some(born) {
            return Err("Process changed or exited; refresh and select it again".into());
        }
        let name = process_name(handle.0).ok_or("Cannot verify process identity")?;
        if !safe(handle.0, pid, &name) {
            return Err("Protected process; termination refused".into());
        }
        TerminateProcess(handle.0, 1).map_err(|_| "Windows refused to end this process")?;
        Ok(format!("Ended {name} (PID {pid})"))
    }
}
pub fn replace(from: &Path, to: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    let from: Vec<_> = from.as_os_str().encode_wide().chain(Some(0)).collect();
    let to: Vec<_> = to.as_os_str().encode_wide().chain(Some(0)).collect();
    unsafe {
        MoveFileExW(
            PCWSTR(from.as_ptr()),
            PCWSTR(to.as_ptr()),
            MOVEFILE_REPLACE_EXISTING,
        )
    }
    .map_err(std::io::Error::other)
}
pub fn task_manager() -> Result<(), String> {
    let root = std::env::var_os("SystemRoot").ok_or("Windows directory unavailable")?;
    std::process::Command::new(Path::new(&root).join("System32/Taskmgr.exe"))
        .spawn()
        .map(|_| ())
        .map_err(|_| "Could not open Task Manager".into())
}
