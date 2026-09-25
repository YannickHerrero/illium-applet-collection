//! Bounded, locked, atomic state. Never lives in Illium's watched config tree.
#![cfg_attr(not(windows), allow(dead_code))]
use fs2::FileExt;
use illigotchi::State;
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::Path,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
const LIMIT: u64 = 65_536;
pub fn lock(dir: &Path) -> Result<File, String> {
    fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(dir.join("state.lock"))
        .map_err(|e| e.to_string())?;
    let start = Instant::now();
    loop {
        match file.try_lock_exclusive() {
            Ok(()) => return Ok(file),
            Err(e) if start.elapsed() >= Duration::from_secs(2) => {
                return Err(format!("Save is busy: {e}"));
            }
            Err(_) => std::thread::sleep(Duration::from_millis(20)),
        }
    }
}
pub fn load(dir: &Path) -> Result<State, String> {
    let path = dir.join("state.json");
    let file = match File::open(&path) {
        Ok(file) => file,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(State::default()),
        Err(e) => return Err(format!("Cannot read save (left untouched): {e}")),
    };
    let mut bytes = Vec::new();
    file.take(LIMIT + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    // Future schemas are not corruption. Leave them untouched for a newer provider.
    if let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes)
        && let Some(version) = value.get("version").and_then(|v| v.as_u64())
        && version != 1
    {
        return Err("Unsupported save version; upgrade the provider or restore a backup".into());
    }
    let parsed = (bytes.len() <= LIMIT as usize)
        .then(|| serde_json::from_slice::<State>(&bytes).ok())
        .flatten();
    if let Some(pet) = parsed
        && pet.validate().is_ok()
    {
        return Ok(pet);
    }
    // Keep the exact corrupt bytes for recovery. No overwrite, even in the
    // unlikely event two recoveries share a timestamp.
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_nanos();
    let backup = dir.join(format!("state-corrupt-{stamp}-{}.json", std::process::id()));
    if backup.exists() {
        return Err("Recovery backup already exists; save left untouched".into());
    }
    fs::rename(&path, &backup).map_err(|e| format!("Cannot preserve corrupt save: {e}"))?;
    Ok(State {
        notice: "Unreadable save preserved as state-corrupt-*.json. A fresh egg is safe here."
            .into(),
        ..State::default()
    })
}
pub fn save(dir: &Path, pet: &State) -> Result<(), String> {
    pet.validate()?;
    let bytes = serde_json::to_vec(pet).map_err(|e| e.to_string())?;
    let temp = dir.join("state.pending");
    let result = (|| {
        let mut file = File::create(&temp).map_err(|e| e.to_string())?;
        file.write_all(&bytes).map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
        drop(file);
        replace(&temp, &dir.join("state.json"))
    })();
    if result.is_err() {
        let _ = fs::remove_file(temp);
    }
    result
}
#[cfg(windows)]
fn replace(from: &Path, to: &Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows::{
        Win32::Storage::FileSystem::{
            MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH, MoveFileExW,
        },
        core::PCWSTR,
    };
    let a: Vec<u16> = from.as_os_str().encode_wide().chain(Some(0)).collect();
    let b: Vec<u16> = to.as_os_str().encode_wide().chain(Some(0)).collect();
    unsafe {
        MoveFileExW(
            PCWSTR(a.as_ptr()),
            PCWSTR(b.as_ptr()),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    }
    .map_err(|e| e.to_string())
}
#[cfg(not(windows))]
fn replace(from: &Path, to: &Path) -> Result<(), String> {
    fs::rename(from, to).map_err(|e| e.to_string())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn roundtrip_corruption_and_future_version() {
        let dir = std::env::temp_dir().join(format!("illigotchi-storage-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        let lock = lock(&dir).unwrap();
        let pet = load(&dir).unwrap();
        save(&dir, &pet).unwrap();
        save(&dir, &pet).unwrap();
        assert_eq!(load(&dir).unwrap().generation, 1);
        fs::write(dir.join("state.json"), b"broken").unwrap();
        assert!(!load(&dir).unwrap().notice.is_empty());
        assert!(fs::read_dir(&dir).unwrap().any(|e| {
            e.unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with("state-corrupt-")
        }));
        fs::write(dir.join("state.json"), br#"{"version":2}"#).unwrap();
        assert!(load(&dir).is_err());
        assert_eq!(
            fs::read(dir.join("state.json")).unwrap(),
            br#"{"version":2}"#
        );
        fs::write(dir.join("state.json"), vec![b' '; LIMIT as usize + 1]).unwrap();
        assert!(!load(&dir).unwrap().notice.is_empty());
        drop(lock);
        fs::remove_dir_all(&dir).unwrap();
    }
    #[test]
    fn lock_serializes_writers_and_releases_on_drop() {
        let dir = std::env::temp_dir().join(format!("illigotchi-lock-{}", std::process::id()));
        let first = lock(&dir).unwrap();
        let second = OpenOptions::new()
            .read(true)
            .write(true)
            .open(dir.join("state.lock"))
            .unwrap();
        assert!(second.try_lock_exclusive().is_err());
        drop(first);
        second.try_lock_exclusive().unwrap();
        drop(second);
        fs::remove_dir_all(dir).unwrap();
    }
}
