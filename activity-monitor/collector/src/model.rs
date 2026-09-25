use serde::{Deserialize, Serialize};
use std::collections::HashMap;

pub const MAX_ROWS: usize = 80;
pub const MAX_GAP_MS: u64 = 12_000;
#[derive(Default, Serialize, Deserialize)]
pub struct Raw {
    pub at: u64,
    pub cpu: Option<(u64, u64)>,    // total (including idle), idle
    pub memory: Option<(u64, u64)>, // total, available physical bytes
    pub network: Option<(String, String, u64, u64)>, // identity, alias, receive, send
    pub disk: Option<(u32, u64, u64)>,
    pub io_at: u64,
}
#[derive(Default, Serialize, Deserialize)]
pub struct Process {
    pub pid: u32,
    pub born: u64,
    pub name: String,
    pub ticks: Option<u64>,
    pub memory: Option<u64>, // working set, not private commit
    pub safe: bool,
    pub cpu: Option<f64>,
}
impl Process {
    pub fn key(&self) -> String {
        format!("{}:{}", self.pid, self.born)
    }
}
#[derive(Default, Serialize, Deserialize)]
pub struct Volume {
    pub name: String,
    pub detail: String,
    pub used: f64,
}
#[derive(Serialize)]
pub struct Segment {
    pub x1: f64,
    pub x2: f64,
    pub y1: f64,
    pub y2: f64,
}
#[derive(Serialize, Deserialize)]
pub struct Point {
    pub at: u64,
    pub cpu: Option<f64>,
    pub ram: Option<f64>,
}
#[derive(Default, Serialize, Deserialize)]
#[serde(default)]
pub struct State {
    pub schema: u32,
    pub raw: Raw,
    pub processes_at: u64,
    pub processes: Vec<Process>,
    pub process_error: String,
    pub volumes_at: u64,
    pub volumes: Vec<Volume>,
    pub history: Vec<Point>,
    pub cpu: Option<f64>,
    pub down: Option<f64>,
    pub up: Option<f64>,
    pub read: Option<f64>,
    pub write: Option<f64>,
    pub query: String,
    pub sort: String,
    pub selection: String,
    pub notice: String,
}
#[derive(Debug, PartialEq)]
pub struct Action {
    pub verb: String,
    pub query: String,
    pub sort: String,
    pub target: String,
}
impl Action {
    pub fn parse(arg: Option<&str>) -> Result<Self, String> {
        let fields: Vec<String> = match arg {
            None => vec!["basic".into(), String::new(), "cpu".into(), String::new()],
            Some("sample") => vec!["sample".into(), String::new(), "cpu".into(), String::new()],
            Some(s) if s.len() <= 2048 => {
                serde_json::from_str(s).map_err(|_| "Invalid action encoding")?
            }
            _ => return Err("Action too long".into()),
        };
        if fields.len() != 4
            || !["basic", "sample", "task-manager", "end"].contains(&fields[0].as_str())
            || !["cpu", "memory", "name", "pid"].contains(&fields[2].as_str())
            || fields[1].chars().count() > 128
        {
            return Err("Unsupported action".into());
        }
        if fields[0] == "end" {
            identity(&fields[3])?;
        }
        Ok(Self {
            verb: fields[0].clone(),
            query: fields[1].clone(),
            sort: fields[2].clone(),
            target: fields[3].clone(),
        })
    }
}
pub fn identity(key: &str) -> Result<(u32, u64), String> {
    let (pid, born) = key.split_once(':').ok_or("Invalid process identity")?;
    let pid = pid.parse::<u32>().map_err(|_| "Invalid PID")?;
    let born = born.parse::<u64>().map_err(|_| "Invalid creation time")?;
    if pid <= 4 || born == 0 {
        return Err("Protected or unidentified process".into());
    }
    Ok((pid, born))
}
pub fn protected(name: &str) -> bool {
    let name = name.to_ascii_lowercase();
    name.starts_with("illium")
        || [
            "activity-monitor.exe",
            "system",
            "registry",
            "smss.exe",
            "csrss.exe",
            "wininit.exe",
            "winlogon.exe",
            "lsass.exe",
            "services.exe",
        ]
        .contains(&name.as_str())
}
pub fn rate(old: u64, new: u64, elapsed: u64) -> Option<f64> {
    if !(200..=MAX_GAP_MS).contains(&elapsed) {
        return None;
    }
    Some(new.checked_sub(old)? as f64 * 1000.0 / elapsed as f64)
}
pub fn cpu_delta(old: Option<(u64, u64)>, new: Option<(u64, u64)>, elapsed: u64) -> Option<f64> {
    if !(200..=MAX_GAP_MS).contains(&elapsed) {
        return None;
    }
    let (old, new) = (old?, new?);
    let total = new.0.checked_sub(old.0)?;
    let idle = new.1.checked_sub(old.1)?;
    if total == 0 || idle > total {
        return None;
    }
    Some((total - idle) as f64 * 100.0 / total as f64)
}
pub fn memory_percent(raw: &Raw) -> Option<f64> {
    let (total, available) = raw.memory?;
    (total > 0 && available <= total).then(|| (total - available) as f64 * 100.0 / total as f64)
}
impl State {
    pub fn update(&mut self, mut raw: Raw) {
        let elapsed = raw.at.saturating_sub(self.raw.at);
        self.cpu = cpu_delta(self.raw.cpu, raw.cpu, elapsed);
        if raw.io_at > 0 {
            let io_elapsed = raw.io_at.saturating_sub(self.raw.io_at);
            self.down = None;
            self.up = None;
            if let (Some(old), Some(new)) = (&self.raw.network, &raw.network)
                && old.0 == new.0
            {
                self.down = rate(old.2, new.2, io_elapsed);
                self.up = rate(old.3, new.3, io_elapsed);
            }
            self.read = None;
            self.write = None;
            if let (Some(old), Some(new)) = (self.raw.disk, raw.disk)
                && old.0 == new.0
            {
                self.read = rate(old.1, new.1, io_elapsed);
                self.write = rate(old.2, new.2, io_elapsed);
            }
        } else {
            raw.network = self.raw.network.clone();
            raw.disk = self.raw.disk;
            raw.io_at = self.raw.io_at;
        }
        self.history
            .retain(|p| p.at <= raw.at && raw.at - p.at <= 60_000);
        self.history.push(Point {
            at: raw.at,
            cpu: self.cpu,
            ram: memory_percent(&raw),
        });
        if self.history.len() > 60 {
            self.history.drain(..self.history.len() - 60);
        }
        self.raw = raw;
    }
    pub fn update_processes(&mut self, mut next: Vec<Process>, at: u64, cpus: u32) {
        let previous: HashMap<_, _> = self
            .processes
            .iter()
            .map(|p| ((p.pid, p.born), p.ticks))
            .collect();
        for p in &mut next {
            p.cpu = previous
                .get(&(p.pid, p.born))
                .copied()
                .flatten()
                .zip(p.ticks)
                .and_then(|(old, new)| rate(old, new, at.saturating_sub(self.processes_at)))
                .map(|ticks_per_second| {
                    (ticks_per_second / 100_000.0 / cpus.max(1) as f64).clamp(0.0, 100.0)
                });
        }
        self.processes = next;
        self.processes_at = at;
        self.process_error.clear();
    }
    pub fn rows(&self) -> (usize, Vec<&Process>) {
        let query = self.query.to_lowercase();
        let mut rows: Vec<_> = self
            .processes
            .iter()
            .filter(|p| {
                p.name.to_lowercase().contains(&query) || p.pid.to_string().contains(&query)
            })
            .collect();
        rows.sort_by(|a, b| {
            let order = match self.sort.as_str() {
                "memory" => b.memory.cmp(&a.memory),
                "name" => a.name.to_lowercase().cmp(&b.name.to_lowercase()),
                "pid" => a.pid.cmp(&b.pid),
                _ => b
                    .cpu
                    .partial_cmp(&a.cpu)
                    .unwrap_or(std::cmp::Ordering::Equal),
            };
            order.then_with(|| a.pid.cmp(&b.pid))
        });
        let total = rows.len();
        rows.truncate(MAX_ROWS);
        (total, rows)
    }
    pub fn chart(&self, ram: bool) -> Vec<Segment> {
        let round = |v: f64| (v.clamp(0.0, 100.0) * 100.0).round() / 100.0;
        self.history
            .windows(2)
            .filter_map(|pair| {
                let (a, b) = (&pair[0], &pair[1]);
                if b.at.saturating_sub(a.at) > MAX_GAP_MS {
                    return None;
                }
                let (y1, y2) = if ram {
                    (a.ram?, b.ram?)
                } else {
                    (a.cpu?, b.cpu?)
                };
                Some(Segment {
                    x1: round(100.0 - self.raw.at.saturating_sub(a.at) as f64 / 600.0),
                    x2: round(100.0 - self.raw.at.saturating_sub(b.at) as f64 / 600.0),
                    y1: round(y1),
                    y2: round(y2),
                })
            })
            .collect()
    }
}
pub fn percent(value: Option<f64>) -> String {
    value.map_or("—".into(), |v| format!("{v:.0}%"))
}
pub fn bytes(value: Option<f64>) -> String {
    value.map_or("—".into(), |mut v| {
        let mut unit = "B";
        for next in ["KiB", "MiB", "GiB", "TiB"] {
            if v < 1024.0 {
                break;
            }
            v /= 1024.0;
            unit = next;
        }
        if unit == "B" {
            format!("{v:.0} {unit}")
        } else {
            format!("{v:.1} {unit}")
        }
    })
}
pub fn throughput(value: Option<f64>) -> String {
    value.map_or("—".into(), |v| format!("{}/s", bytes(Some(v))))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn counter_edges() {
        assert_eq!(rate(0, 2000, 2000), Some(1000.0));
        for elapsed in [0, 199, 13000] {
            assert_eq!(rate(1, 2, elapsed), None);
        }
        assert_eq!(rate(10, 9, 1000), None);
        assert_eq!(
            cpu_delta(Some((100, 50)), Some((200, 75)), 1000),
            Some(75.0)
        );
        assert_eq!(cpu_delta(Some((100, 50)), Some((110, 75)), 1000), None);
    }
    #[test]
    fn pid_reuse_is_not_cpu_usage() {
        let mut s = State::default();
        s.update_processes(
            vec![Process {
                pid: 42,
                born: 1,
                ticks: Some(1),
                ..Default::default()
            }],
            1000,
            4,
        );
        s.update_processes(
            vec![Process {
                pid: 42,
                born: 2,
                ticks: Some(20_000_001),
                ..Default::default()
            }],
            3000,
            4,
        );
        assert_eq!(s.processes[0].cpu, None);
        s.update_processes(
            vec![Process {
                pid: 42,
                born: 2,
                ticks: Some(40_000_001),
                ..Default::default()
            }],
            5000,
            4,
        );
        assert_eq!(s.processes[0].cpu, Some(25.0));
    }
    #[test]
    fn network_switch_and_missing_data_reset_rates() {
        let mut s = State::default();
        s.update(Raw {
            at: 1000,
            network: Some(("A".into(), "Wi-Fi".into(), 1, 2)),
            ..Default::default()
        });
        s.update(Raw {
            at: 3000,
            network: Some(("B".into(), "Ethernet".into(), 999, 999)),
            ..Default::default()
        });
        assert!(s.down.is_none());
        s.update(Raw {
            at: 5000,
            ..Default::default()
        });
        assert!(s.down.is_none());
    }
    #[test]
    fn bounded_unicode_search_and_sort() {
        let s = State {
            query: "ÉD".into(),
            sort: "memory".into(),
            processes: (0..100)
                .map(|pid| Process {
                    pid,
                    name: "Éditeur.exe".into(),
                    memory: Some(pid as u64),
                    ..Default::default()
                })
                .collect(),
            ..Default::default()
        };
        let (total, rows) = s.rows();
        assert_eq!(total, 100);
        assert_eq!(rows.len(), 80);
        assert_eq!(rows[0].pid, 99);
    }
    #[test]
    fn actions_require_full_identity() {
        assert!(identity("42").is_err());
        assert!(identity("4:123").is_err());
        assert!(identity("42:0").is_err());
        assert_eq!(identity("42:123").unwrap(), (42, 123));
        assert!(Action::parse(Some(r#"["end","","cpu","42"]"#)).is_err());
        assert!(Action::parse(Some(r#"["shell","","cpu",""]"#)).is_err());
        assert!(protected("ILLIUM.exe"));
        assert!(protected("lsass.exe"));
        assert!(!protected("notepad.exe"));
    }
    #[test]
    fn closed_samples_do_not_corrupt_io_baselines() {
        let mut s = State::default();
        s.update(Raw {
            at: 1000,
            io_at: 1000,
            network: Some(("A".into(), "Wi-Fi".into(), 0, 0)),
            disk: Some((0, 0, 0)),
            ..Default::default()
        });
        s.update(Raw {
            at: 2000,
            ..Default::default()
        });
        assert_eq!(s.raw.io_at, 1000);
        s.update(Raw {
            at: 3000,
            io_at: 3000,
            network: Some(("A".into(), "Wi-Fi".into(), 2000, 4000)),
            disk: Some((0, 6000, 8000)),
            ..Default::default()
        });
        assert_eq!(s.down, Some(1000.0));
        assert_eq!(s.read, Some(3000.0));
        s.update(Raw {
            at: 5000,
            io_at: 5000,
            network: Some(("B".into(), "Ethernet".into(), 10000, 10000)),
            disk: Some((1, 100000, 100000)),
            ..Default::default()
        });
        assert_eq!(s.down, None);
        assert_eq!(s.read, None);
    }
    #[test]
    fn invalid_memory_is_unavailable() {
        assert_eq!(
            memory_percent(&Raw {
                memory: Some((100, 101)),
                ..Default::default()
            }),
            None
        );
        assert_eq!(
            memory_percent(&Raw {
                memory: Some((0, 0)),
                ..Default::default()
            }),
            None
        );
    }
    #[test]
    fn history_is_bounded_and_gaps_are_not_interpolated() {
        let mut s = State::default();
        for at in (0..200000).step_by(500) {
            s.update(Raw {
                at,
                memory: Some((100, 50)),
                ..Default::default()
            });
        }
        assert!(s.history.len() <= 120);
        assert!(!s.chart(true).is_empty());
        s.update(Raw {
            at: 230000,
            memory: Some((100, 50)),
            ..Default::default()
        });
        assert!(s.chart(true).iter().all(|segment| segment.x2 < 100.0));
    }
}
