use windows::Win32::{
    Foundation::{CloseHandle, FILETIME, HANDLE},
    System::{
        Diagnostics::ToolHelp::{
            CreateToolhelp32Snapshot, PROCESSENTRY32W, Process32FirstW, Process32NextW,
            TH32CS_SNAPPROCESS,
        },
        SystemInformation::GetLocalTime,
        Threading::{GetProcessTimes, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION},
        WindowsProgramming::QueryUnbiasedInterruptTime,
    },
};
pub fn local_schedule() -> (u16, u16) {
    let time = unsafe { GetLocalTime() };
    (time.wDayOfWeek, time.wHour * 60 + time.wMinute)
}

struct Handle(HANDLE);
impl Drop for Handle {
    fn drop(&mut self) {
        unsafe {
            let _ = CloseHandle(self.0);
        }
    }
}
/// The manifest starts this executable directly, so its parent is Illium.
/// Creation time disambiguates PID reuse; unbiased interrupt time excludes sleep.
pub fn clock() -> Result<(String, u64), String> {
    unsafe {
        let snapshot =
            Handle(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0).map_err(|e| e.to_string())?);
        let mut entry = PROCESSENTRY32W {
            dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
            ..Default::default()
        };
        Process32FirstW(snapshot.0, &mut entry).map_err(|e| e.to_string())?;
        let parent = loop {
            if entry.th32ProcessID == std::process::id() {
                break entry.th32ParentProcessID;
            }
            Process32NextW(snapshot.0, &mut entry).map_err(|e| e.to_string())?;
        };
        let handle = Handle(
            OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, parent)
                .map_err(|e| e.to_string())?,
        );
        let mut created = FILETIME::default();
        let mut exit = FILETIME::default();
        let mut kernel = FILETIME::default();
        let mut user = FILETIME::default();
        GetProcessTimes(handle.0, &mut created, &mut exit, &mut kernel, &mut user)
            .map_err(|e| e.to_string())?;
        let identity = ((created.dwHighDateTime as u64) << 32) | created.dwLowDateTime as u64;
        let mut ticks = 0;
        QueryUnbiasedInterruptTime(&mut ticks)
            .ok()
            .map_err(|e| e.to_string())?;
        Ok((format!("{parent}:{identity}"), ticks / 10_000))
    }
}
