mod storage;
#[cfg(windows)]
mod win;

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
    let _lock = storage::lock(&dir)?;
    let (session, now) = win::clock()?;
    let mut pet = storage::load(&dir)?;
    pet.advance(&session, now);
    pet.action(action, now)?;
    storage::save(&dir, &pet)?;
    println!("{}", pet.snapshot());
    Ok(())
}
#[cfg(not(windows))]
fn run() -> Result<(), String> {
    Err("The provider runs on Windows; the simulation tests are portable".into())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("Winagotchi: {error}");
        std::process::exit(1);
    }
}
