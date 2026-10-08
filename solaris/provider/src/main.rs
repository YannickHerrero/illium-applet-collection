use std::process::ExitCode;

use chrono::{DateTime, Duration, Utc};
use serde_json::{Value, json};
use solaris::TICK_RATE_MS;
use solaris::game::{Achievement, GameState, Producer, calculate_bulk_cost};
use solaris::save::{self, SaveData};

// Illium polls every minute, so a longer gap means it was not running (sleep,
// shutdown): credited like the game's own offline progress, not simulated.
const LIVE_GAP_SECS: i64 = 90;
const MAX_CLICKS: u64 = 100;
const UPGRADES_SHOWN: usize = 8;
const SUFFIXES: [&str; 12] = [
    "", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc",
];

fn main() -> ExitCode {
    let words: Vec<String> = std::env::args()
        .skip(1)
        .flat_map(|arg| {
            arg.split_whitespace()
                .map(str::to_owned)
                .collect::<Vec<_>>()
        })
        .collect();
    match run(&words) {
        Ok(snapshot) => {
            println!("{snapshot}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}

fn run(words: &[String]) -> Result<Value, String> {
    let error = |e: std::io::Error| e.to_string();
    let label = save::resolve_save_label(None)
        .map_err(error)?
        .unwrap_or_else(|| "main".to_owned());
    let Some(lock) = save::lock_save(&label).map_err(error)? else {
        return Ok(json!({ "in_terminal": true, "bar_label": "" }));
    };
    let mut data = save::load_game(&label)
        .map_err(error)?
        .unwrap_or_else(|| SaveData {
            game_state: GameState::new(),
            last_save: Utc::now(),
        });
    data.game_state.migrate_all_time_counters();
    catch_up(&mut data, Utc::now());
    let words: Vec<&str> = words.iter().map(String::as_str).collect();
    act(&mut data.game_state, &words);
    save::save_game(&label, &data).map_err(error)?;
    drop(lock);
    Ok(snapshot(&mut data.game_state))
}

fn catch_up(data: &mut SaveData, now: DateTime<Utc>) {
    let elapsed = now - data.last_save;
    if elapsed.num_seconds() > LIVE_GAP_SECS {
        data.game_state
            .apply_offline_progress(elapsed.num_seconds() as u64);
        data.last_save = now;
        return;
    }
    // Leftover milliseconds stay owed to the next run.
    let ticks = elapsed.num_milliseconds().max(0) as u64 / TICK_RATE_MS;
    for _ in 0..ticks {
        data.game_state.tick();
    }
    data.last_save += Duration::milliseconds((ticks * TICK_RATE_MS) as i64);
}

fn act(game: &mut GameState, words: &[&str]) {
    match words {
        ["mine", clicks] => {
            for _ in 0..clicks.parse::<u64>().unwrap_or(0).min(MAX_CLICKS) {
                game.manual_mine();
            }
        }
        ["buy", id, amount] => {
            let Some(producer) = id.parse().ok().and_then(producer) else {
                return;
            };
            let owned = game.producer_count(producer.id);
            let quantity = match *amount {
                "max" => game.max_affordable(producer, owned, u64::MAX),
                amount => amount.parse().unwrap_or(0),
            };
            if quantity > 0 {
                game.buy_producer(producer.id, quantity);
            }
        }
        ["upgrade", id] => {
            if let Ok(id) = id.parse() {
                game.buy_upgrade(id);
            }
        }
        _ => {}
    }
}

fn producer(id: u32) -> Option<&'static Producer> {
    Producer::all().iter().find(|p| p.id == id)
}

fn snapshot(game: &mut GameState) -> Value {
    let mut achievement = String::new();
    while let Some(unlocked) = game.pop_new_achievement() {
        achievement = unlocked.name.to_owned();
    }
    let (energy_scaled, unit) = scale(game.energy);
    let ratio = if unit.is_empty() {
        1.0
    } else {
        game.energy / energy_scaled
    };
    let producers: Vec<Value> = game
        .visible_producers()
        .into_iter()
        .map(|(_, p)| {
            let owned = game.producer_count(p.id);
            let max = game.max_affordable(p, owned, u64::MAX);
            let cost = |quantity| calculate_bulk_cost(p.base_cost, owned, quantity, p.id);
            json!({
                "id": p.id.to_string(),
                "cost_1_scaled": cost(1) / ratio,
                "cost_10_scaled": cost(10) / ratio,
                "name": p.name,
                "owned": owned.to_string(),
                "rate": rate(game.producer_total_rate(p.id)),
                "cost_1": compact(cost(1)),
                "cost_10": compact(cost(10)),
                "cost_max": compact(cost(max.max(1))),
                "max": max.to_string(),
            })
        })
        .collect();
    let mut available = game.available_upgrades();
    available.sort_by(|a, b| a.cost.total_cmp(&b.cost));
    let upgrades: Vec<Value> = available
        .iter()
        .take(UPGRADES_SHOWN)
        .map(|u| {
            let cost = game.get_upgrade_cost(u);
            json!({
                "id": u.id.to_string(),
                "name": u.name,
                "description": u.description,
                "cost": compact(cost),
                "cost_scaled": cost / ratio,
            })
        })
        .collect();
    let eps = game.total_energy_per_second();
    let click = game.effective_manual_power();
    json!({
        "in_terminal": false,
        "bar_label": rate(eps),
        "energy_scaled": energy_scaled,
        "unit": unit,
        "eps_scaled": eps / ratio,
        "click_scaled": click / ratio,
        "eps": rate(eps),
        "click": compact(click),
        "producers": producers,
        "upgrades": upgrades,
        "upgrades_available": available.len() as i64,
        "achievements": format!("{}/{}", game.achievements_unlocked.len(), Achievement::all().len()),
        "achievement": achievement,
        "chips": game.stellar_chips.to_string(),
        "ascension_chips": game.calculate_potential_stellar_chips().to_string(),
    })
}

/// Splits a value into a mantissa below 1000 and its suffix, so the popup can
/// keep counting in that unit between two runs.
fn scale(value: f64) -> (f64, String) {
    if value.is_nan() || value < 1000.0 {
        return (value, String::new());
    }
    let group = (value.log10() / 3.0).floor() as usize;
    let unit = match SUFFIXES.get(group) {
        Some(suffix) => (*suffix).to_owned(),
        None => format!("e{}", group * 3),
    };
    (value / 10f64.powi(group as i32 * 3), unit)
}

fn compact(value: f64) -> String {
    match scale(value) {
        (v, unit) if unit.is_empty() && v < 10.0 => format!("{:.1}", (v * 10.0).floor() / 10.0),
        (v, unit) if unit.is_empty() => format!("{}", v.floor()),
        (v, unit) => format!("{:.2}{unit}", (v * 100.0).floor() / 100.0),
    }
}

fn rate(value: f64) -> String {
    format!("{}/s", compact(value))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn save(game_state: GameState, last_save: DateTime<Utc>) -> SaveData {
        SaveData {
            game_state,
            last_save,
        }
    }

    #[test]
    fn short_gaps_are_played_tick_by_tick_and_keep_the_remainder() {
        let mut game = GameState::new();
        game.producers_owned.insert(1, 10);
        let start = Utc::now();
        let mut data = save(game, start);
        catch_up(&mut data, start + Duration::milliseconds(30_050));
        assert_eq!(data.game_state.ticks_played, 300);
        assert!(data.game_state.energy >= 30.0 - 1e-6);
        assert_eq!(data.last_save, start + Duration::seconds(30));
    }

    #[test]
    fn long_gaps_use_the_offline_formula() {
        let mut game = GameState::new();
        game.producers_owned.insert(1, 10);
        let start = Utc::now();
        let mut data = save(game, start);
        let now = start + Duration::hours(10);
        catch_up(&mut data, now);
        assert_eq!(data.game_state.ticks_played, 0);
        assert!((data.game_state.energy - 8.0 * 3600.0).abs() < 1e-3);
        assert_eq!(data.last_save, now);
    }

    #[test]
    fn actions_mine_and_buy_within_limits() {
        let mut game = GameState::new();
        act(&mut game, &["mine", "1000"]);
        assert_eq!(game.total_manual_clicks, MAX_CLICKS);
        act(&mut game, &["buy", "1", "max"]);
        assert_eq!(game.producer_count(1), 4);
        act(&mut game, &["buy", "99", "1"]);
        act(&mut game, &["buy", "1", "x"]);
        act(&mut game, &["upgrade", "nope"]);
    }

    #[test]
    fn numbers_are_compact() {
        assert_eq!(compact(3.75), "3.7");
        assert_eq!(compact(999.9), "999");
        assert_eq!(compact(24_900.0), "24.90K");
        assert_eq!(compact(1.5e9), "1.50B");
        assert_eq!(compact(2e40), "20.00e39");
        assert_eq!(scale(f64::NAN).1, "");
    }

    #[test]
    fn snapshot_reports_the_unit_of_the_counter() {
        let mut game = GameState::new();
        game.energy = 2.5e6;
        let value = snapshot(&mut game);
        assert_eq!(value["unit"], "M");
        assert_eq!(value["bar_label"], "0.0/s");
        assert!((value["energy_scaled"].as_f64().unwrap() - 2.5).abs() < 1e-9);
        let cost_10 = value["producers"][0]["cost_10_scaled"].as_f64().unwrap() * 1e6;
        assert!((cost_10 - calculate_bulk_cost(15.0, 0, 10, 1)).abs() < 1e-6);
    }
}
