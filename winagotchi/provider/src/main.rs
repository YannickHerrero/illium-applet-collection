mod storage;
#[cfg(windows)]
mod win;

#[cfg(any(windows, test))]
fn work_day_setting(value: Option<&str>) -> Result<bool, String> {
    match value {
        None | Some("false") => Ok(false),
        Some("true") => Ok(true),
        _ => Err("WINARCHY_APPLET_WORK_DAY must be true or false".into()),
    }
}

#[cfg(windows)]
fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() > 1 {
        return Err("Expected one action argument".into());
    }
    let action = args.first().map(String::as_str).unwrap_or("refresh");
    let dir = match std::env::var_os("WINARCHY_APPLET_STATE_DIR") {
        Some(path) => std::path::PathBuf::from(path),
        None => std::path::PathBuf::from(
            std::env::var_os("LOCALAPPDATA").ok_or("LOCALAPPDATA is missing")?,
        )
        .join("Winarchy/winagotchi"),
    };
    if !dir.is_absolute() {
        return Err("State directory must be absolute".into());
    }
    let work_day = work_day_setting(std::env::var("WINARCHY_APPLET_WORK_DAY").ok().as_deref())?;
    let _lock = storage::lock(&dir)?;
    let (session, now) = win::clock()?;
    let mut pet = storage::load(&dir)?;
    // Configuration is authoritative, including for existing saves.
    pet.work_day = work_day;
    let (weekday, minute) = win::local_schedule();
    pet.advance_scheduled(&session, now, weekday, minute);
    pet.action(action, now)?;
    storage::save(&dir, &pet)?;
    println!("{}", pet.snapshot());
    Ok(())
}
#[cfg(not(windows))]
fn run() -> Result<(), String> {
    Err("The provider runs on Windows; the simulation tests are portable".into())
}
#[test]
fn work_day_config_values() {
    assert!(!work_day_setting(None).unwrap());
    assert!(!work_day_setting(Some("false")).unwrap());
    assert!(work_day_setting(Some("true")).unwrap());
    assert!(work_day_setting(Some("yes")).is_err());
}

fn main() {
    if let Err(error) = run() {
        eprintln!("Winagotchi: {error}");
        std::process::exit(1);
    }
}
