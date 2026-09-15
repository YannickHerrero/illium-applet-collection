use activity_monitor as model;
#[cfg(windows)]
mod win;
use model::*;
use serde_json::{Value, json};

fn render(s: &State) -> Value {
    let ram = memory_percent(&s.raw);
    let ram_detail = s.raw.memory.filter(|(t, a)| *t > 0 && a <= t).map_or(
        "Physical memory unavailable".into(),
        |(total, available)| {
            format!(
                "{} / {} · {} available",
                bytes(Some((total - available) as f64)),
                bytes(Some(total as f64)),
                bytes(Some(available as f64))
            )
        },
    );
    let details_fresh = s.raw.io_at > 0 && s.raw.at.saturating_sub(s.raw.io_at) <= MAX_GAP_MS;
    let processes_fresh = s.processes_at > 0
        && s.raw.at.saturating_sub(s.processes_at) <= MAX_GAP_MS
        && s.process_error.is_empty();
    let (matches, rows) = s.rows();
    let to_row = |p: &Process| {
        json!({
            "key":p.key(),"pid":p.pid.to_string(),"name":if p.name.chars().count()>96 { format!("{}…",p.name.chars().take(96).collect::<String>()) } else { p.name.clone() },
            "cpu":if processes_fresh { p.cpu.map_or("—".into(), |v| format!("{v:.1}%")) } else { "—".into() },
            "memory":if processes_fresh { bytes(p.memory.map(|v|v as f64)) } else { "—".into() },
            "can_end":p.safe && processes_fresh,
        })
    };
    let processes: Vec<_> = rows.iter().map(|p| to_row(p)).collect();
    let mut busiest: Vec<_> = s.processes.iter().collect();
    busiest.sort_by(|a, b| {
        b.cpu
            .partial_cmp(&a.cpu)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.pid.cmp(&b.pid))
    });
    let busiest: Vec<_> = busiest.into_iter().take(3).map(to_row).collect();
    let rate = |value| throughput(if details_fresh { value } else { None });
    json!({
        "bar_label":format!("{} · {}",percent(s.cpu),percent(ram)),
        "cpu":percent(s.cpu),"ram":percent(ram),"ram_detail":ram_detail,
        "cpu_chart":s.chart(false),"ram_chart":s.chart(true),
        "uptime":format!("Uptime {}d {}h {}m",s.raw.at/86400000,s.raw.at/3600000%24,s.raw.at/60000%60),
        "network_name":s.raw.network.as_ref().map_or("No physical adapter".into(),|r|r.1.clone()),
        "down":rate(s.down),"up":rate(s.up),"disk_read":rate(s.read),"disk_write":rate(s.write),
        "disk_name":s.raw.disk.map_or("Disk unavailable".into(),|d|format!("Physical disk {}",d.0)),
        "volumes":s.volumes,"processes":processes,"busiest":busiest,
        "selected_key":s.selection,"selected_index":rows.iter().position(|p|p.key()==s.selection).map_or(-1,|i|i as i32),
        "process_summary":if s.process_error.is_empty() { format!("{} of {} matches · {} processes sampled",rows.len(),matches,s.processes.len()) } else { s.process_error.clone() },
        "status":if details_fresh { "Live · 60s history" } else { "Details paused · CPU/RAM every 5s" },
        "notice":s.notice,
    })
}

#[cfg(windows)]
fn run() -> Result<Value, Box<dyn std::error::Error>> {
    use std::{
        fs::{self, File, OpenOptions},
        io::{Read, Write},
        path::PathBuf,
    };
    let started = std::time::Instant::now();
    let arg = std::env::args().nth(1);
    if arg.as_deref() == Some("--diagnose") {
        return Ok(win::diagnose());
    }
    let action = Action::parse(arg.as_deref())?;
    let directory = if let Some(path) = std::env::var_os("WINARCHY_APPLET_CACHE_PATH") {
        PathBuf::from(path)
    } else {
        PathBuf::from(std::env::var_os("LOCALAPPDATA").ok_or("LOCALAPPDATA unavailable")?)
            .join("Winarchy/cache/activity-monitor")
    };
    fs::create_dir_all(&directory)?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(directory.join("state.lock"))?;
    // Also serialize across configuration generations, not just within one runtime.
    let mut acquired = false;
    for _ in 0..20 {
        if lock.try_lock().is_ok() {
            acquired = true;
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
    if !acquired {
        return Err("Collector cache is busy".into());
    }
    let cache = directory.join("state.json");
    let mut state = File::open(&cache)
        .ok()
        .and_then(|f| {
            let mut input = Vec::new();
            f.take(4 * 1024 * 1024 + 1).read_to_end(&mut input).ok()?;
            if input.len() > 4 * 1024 * 1024 {
                return None;
            }
            serde_json::from_slice::<State>(&input).ok()
        })
        .unwrap_or_default();
    let now = win::now();
    if state.schema != 1 || now < state.raw.at {
        state = State {
            schema: 1,
            ..Default::default()
        };
    }
    if action.verb != "basic" {
        state.query = action.query;
        state.sort = action.sort;
        if action.verb != "end" {
            state.selection = action.target.clone();
        }
    }
    match action.verb.as_str() {
        "end" => {
            // Allow time to read the confirmation, but require a recently offered target.
            // The Windows adapter revalidates creation time and critical status.
            state.notice = if now.saturating_sub(state.processes_at) <= 300_000
                && state
                    .processes
                    .iter()
                    .any(|p| p.key() == action.target && p.safe)
            {
                win::terminate(&action.target).unwrap_or_else(|e| e)
            } else {
                "Selection expired; refresh and select the process again".into()
            };
        }
        "task-manager" => {
            state.notice = win::task_manager().map_or_else(|e| e, |_| "Opened Task Manager".into());
        }
        _ => {}
    }
    let detail = action.verb != "basic";
    let sample_detail =
        detail && (state.raw.io_at == 0 || now.saturating_sub(state.raw.io_at) >= 1000);
    if sample_detail || now.saturating_sub(state.raw.at) >= 500 || state.raw.at == 0 {
        state.update(win::sample(sample_detail));
    }
    if detail
        && (state.processes_at == 0
            || now.saturating_sub(state.processes_at) >= 1000
            || action.verb == "end")
    {
        match win::processes() {
            Ok(processes) => state.update_processes(processes, win::now(), win::cpus()),
            Err(error) => {
                state.process_error = error;
            }
        }
        if state.volumes_at == 0 || now.saturating_sub(state.volumes_at) >= 60000 {
            state.volumes = win::volumes();
            state.volumes_at = now;
        }
    }
    let mut output = render(&state);
    let encoded = serde_json::to_vec(&state)?;
    if encoded.len() > 4 * 1024 * 1024 {
        return Err("Collector state exceeds 4 MiB".into());
    }
    let temporary = directory.join("state.next");
    {
        let mut file = File::create(&temporary)?;
        file.write_all(&encoded)?;
    }
    win::replace(&temporary, &cache)?;
    output["collector_ms"] = json!(started.elapsed().as_millis() as u64);
    Ok(output)
}
#[cfg(windows)]
fn main() {
    match run().and_then(|value| Ok(serde_json::to_string(&value)?)) {
        Ok(output) if output.len() <= 60 * 1024 => println!("{output}"),
        Ok(_) => {
            eprintln!("Collector output exceeds 60 KiB");
            std::process::exit(1);
        }
        Err(error) => {
            eprintln!("Activity Monitor: {error}");
            std::process::exit(1);
        }
    }
}
#[cfg(not(windows))]
fn main() {
    eprintln!("The collector runs on Windows; portable model tests can run here.");
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unavailable_is_not_zero() {
        let data = render(&State::default());
        assert_eq!(data["cpu"], "—");
        assert_eq!(data["down"], "—");
        assert_eq!(data["bar_label"], "— · —");
    }
    #[test]
    fn output_stays_bounded_and_does_not_expose_command_lines() {
        let s = State {
            processes: (0..4096)
                .map(|pid| Process {
                    pid,
                    name: "界".repeat(260),
                    ..Default::default()
                })
                .collect(),
            ..Default::default()
        };
        assert!(serde_json::to_vec(&render(&s)).unwrap().len() < 60 * 1024);
        assert_eq!(render(&s)["processes"].as_array().unwrap().len(), 80);
        assert!(render(&s)["processes"][0].get("ticks").is_none());
    }
}
