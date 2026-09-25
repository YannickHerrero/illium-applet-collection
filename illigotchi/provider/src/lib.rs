//! Independent room-only port of SLcode777/omagotchi (MIT), revision c04d94a.
//! No wall-clock aging, package probes, networking or audio.
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub version: u32,
    pub generation: u32,
    pub form: String,
    pub age_minutes: u32,
    pub care_sum: f64,
    pub care_count: u32,
    pub needs: [f64; 5], // hunger, dirt, tiredness, boredom, loneliness; high = needs care
    pub sleeping: bool,
    #[serde(default)]
    pub work_day: bool,
    #[serde(default)]
    pub paused: bool,
    pub session: String,
    pub last_ms: u64,
    pub remainder_ms: u64,
    pub animation: String,
    pub animation_until_ms: u64,
    pub notice: String,
}
impl Default for State {
    fn default() -> Self {
        Self {
            version: 1,
            generation: 1,
            form: "egg".into(),
            age_minutes: 0,
            care_sum: 0.0,
            care_count: 0,
            needs: [0.0; 5],
            sleeping: false,
            work_day: false,
            paused: false,
            session: String::new(),
            last_ms: 0,
            remainder_ms: 0,
            animation: String::new(),
            animation_until_ms: 0,
            notice: String::new(),
        }
    }
}
impl State {
    pub fn stage(&self) -> &str {
        match self.form.as_str() {
            "egg" => "egg",
            "baby" => "baby",
            "child" => "child",
            "teen_neat" | "teen_scruffy" => "teen",
            _ => "adult",
        }
    }
    pub fn validate(&self) -> Result<(), String> {
        if self.version != 1 {
            return Err("Unsupported save version; the save was left untouched".into());
        }
        let forms = [
            "egg",
            "baby",
            "child",
            "teen_neat",
            "teen_scruffy",
            "adult_ace",
            "adult_ok",
            "adult_gremlin",
        ];
        let age_ok = match self.stage() {
            "egg" => self.age_minutes < 5,
            "baby" => (5..70).contains(&self.age_minutes),
            "child" => (70..550).contains(&self.age_minutes),
            "teen" => (550..1510).contains(&self.age_minutes),
            _ => self.age_minutes >= 1510,
        };
        if !forms.contains(&self.form.as_str())
            || !age_ok
            || self.generation == 0
            || (self.paused && !self.work_day)
            || (self.stage() == "egg"
                && (self.sleeping || !self.animation.is_empty() || self.needs != [0.0; 5]))
            || self.remainder_ms >= 60_000
            || self.session.len() > 128
            || self.notice.len() > 512
            || !self.care_sum.is_finite()
            || self.care_sum < 0.0
            || self.care_sum > self.care_count as f64 * 100.0 + 0.001
            || self.care_count > self.age_minutes
            || self
                .needs
                .iter()
                .any(|v| !v.is_finite() || !(0.0..=100.0).contains(v))
            || !["", "eat", "wash", "pet", "play"].contains(&self.animation.as_str())
        {
            return Err("Invalid pet save".into());
        }
        Ok(())
    }
    pub fn happiness(&self) -> f64 {
        100.0 - self.needs.iter().copied().fold(0.0, f64::max)
    }
    pub fn care_average(&self) -> f64 {
        if self.care_count == 0 {
            100.0
        } else {
            self.care_sum / self.care_count as f64
        }
    }
    /// Local Windows weekday (Sunday = 0) and minute of day only gate activity;
    /// elapsed simulation time still comes exclusively from unbiased uptime.
    pub fn advance_scheduled(&mut self, session: &str, now: u64, weekday: u16, minute: u16) {
        let paused =
            self.work_day && !((1..=5).contains(&weekday) && (540..1080).contains(&minute));
        // Do not charge either boundary interval, including the first morning poll.
        if paused || self.paused {
            self.last_ms = now;
            self.animation.clear();
            self.animation_until_ms = 0;
        }
        self.paused = paused;
        self.advance(session, now);
    }
    /// The clock is Windows unbiased uptime (excludes sleep/hibernation).
    /// Parent PID + creation time identifies an Illium run. Gaps over 90s
    /// are treated as absence, not catch-up; normal manifest polling is 30s.
    pub fn advance(&mut self, session: &str, now: u64) {
        let delta = now.checked_sub(self.last_ms).filter(|d| *d <= 90_000);
        if self.session == session
            && let Some(delta) = delta
        {
            self.remainder_ms += delta;
            while self.remainder_ms >= 60_000 {
                self.remainder_ms -= 60_000;
                self.minute();
            }
        } else {
            self.animation.clear();
            self.animation_until_ms = 0;
        }
        self.session = session.into();
        self.last_ms = now;
        if now >= self.animation_until_ms {
            self.animation.clear();
        }
    }
    fn minute(&mut self) {
        if self.stage() != "egg" {
            let rates = match self.stage() {
                "baby" => [1.5, 1.0, 2.0, 0.5],
                "child" => [1.0, 1.0, 1.0, 1.5],
                "teen" => [2.0, 1.0, 0.8, 0.5],
                _ => [1.0; 4],
            };
            self.needs[0] += 0.33 * rates[0];
            self.needs[1] += 0.21 * rates[1];
            if self.sleeping {
                self.needs[2] = (self.needs[2] - 2.2).max(0.0);
                if self.needs[2] <= 5.0 {
                    self.sleeping = false;
                }
            } else {
                self.needs[2] += 0.28 * rates[2];
                if self.needs[2] >= 60.0 {
                    self.sleeping = true;
                }
            }
            self.needs[3] += 0.45 * rates[3];
            self.needs[4] += 0.12;
            for need in &mut self.needs {
                *need = need.clamp(0.0, 100.0);
            }
        }
        self.age_minutes = self.age_minutes.saturating_add(1);
        // Keep aggregates bounded even for a pet kept for years.
        if self.care_count == u32::MAX {
            self.care_sum /= 2.0;
            self.care_count /= 2;
        }
        self.care_sum += self.happiness();
        self.care_count += 1;
        let next = match self.stage() {
            "egg" if self.age_minutes >= 5 => Some("baby"),
            "baby" if self.age_minutes >= 70 => Some("child"),
            "child" if self.age_minutes >= 550 => Some(if self.care_average() >= 55.0 {
                "teen_neat"
            } else {
                "teen_scruffy"
            }),
            "teen" if self.age_minutes >= 1510 => {
                Some(match (self.form.as_str(), self.care_average()) {
                    ("teen_neat", c) if c >= 75.0 => "adult_ace",
                    ("teen_neat", c) if c >= 40.0 => "adult_ok",
                    (_, c) if c >= 75.0 => "adult_ok",
                    _ => "adult_gremlin",
                })
            }
            _ => None,
        };
        if let Some(form) = next {
            self.form = form.into();
            self.care_sum = 0.0;
            self.care_count = 0;
            self.animation.clear();
            self.notice = if form == "baby" {
                "The egg hatched!".into()
            } else {
                format!("Your companion grew into {}!", self.form_label())
            };
        }
    }
    pub fn form_label(&self) -> &str {
        match self.form.as_str() {
            "egg" => "an egg",
            "baby" => "a baby",
            "child" => "a child",
            "teen_neat" => "a neat teen",
            "teen_scruffy" => "a scruffy teen",
            "adult_ace" => "an ace adult",
            "adult_ok" => "an easygoing adult",
            _ => "a gremlin adult",
        }
    }
    pub fn action(&mut self, action: &str, now: u64) -> Result<(), String> {
        if action == "refresh" {
            return Ok(());
        }
        if action == "dismiss-notice" {
            self.notice.clear();
            return Ok(());
        }
        if let Some(generation) = action.strip_prefix("farewell ") {
            if self.stage() != "adult" || generation.parse::<u32>().ok() != Some(self.generation) {
                return Err("This farewell no longer matches the current adult".into());
            }
            let generation = self
                .generation
                .checked_add(1)
                .ok_or("Generation limit reached")?;
            *self = Self {
                generation,
                work_day: self.work_day,
                paused: self.paused,
                session: self.session.clone(),
                last_ms: now,
                notice: "A fond farewell. A new egg begins the next generation.".into(),
                ..Self::default()
            };
            return Ok(());
        }
        if self.paused {
            return Err("Your companion is resting".into());
        }
        if self.stage() == "egg" {
            return Err("Let the egg warm up first".into());
        }
        match action {
            "feed" => {
                self.needs[0] = (self.needs[0] - 35.0).max(0.0);
                self.animation = "eat".into();
            }
            "pet" => {
                self.needs[4] = (self.needs[4] - 10.0).max(0.0);
                if self.stage() == "baby" {
                    self.needs[3] = (self.needs[3] - 10.0).max(0.0);
                }
                self.animation = "pet".into();
            }
            "play" if self.stage() != "baby" => {
                self.needs[3] = (self.needs[3] - 25.0).max(0.0);
                self.needs[2] = (self.needs[2] + 3.0).min(100.0);
                self.animation = "play".into();
            }
            a if a.starts_with("wash ") => {
                let amount: f64 = a[5..].parse().map_err(|_| "Invalid scrub amount")?;
                if !amount.is_finite() || !(0.0..=25.0).contains(&amount) {
                    return Err("Invalid scrub amount".into());
                }
                self.needs[1] = (self.needs[1] - amount).max(0.0);
                self.animation = "wash".into();
            }
            _ => return Err("Unknown or unavailable pet action".into()),
        }
        self.sleeping = false; // tired pets settle back down on the next minute tick
        self.animation_until_ms = now.saturating_add(3_000);
        Ok(())
    }
    pub fn snapshot(&self) -> serde_json::Value {
        let sleeping = self.sleeping || (self.paused && self.stage() != "egg");
        let mood = if self.paused {
            "Zzz…"
        } else if self.stage() == "egg" {
            "Warming up…"
        } else if self.sleeping {
            "Zzz…"
        } else if self.needs[0] >= 60.0 {
            "Hungry — time for a snack!"
        } else if self.needs[1] >= 60.0 {
            "Bath time — rub to scrub!"
        } else if self.needs[2] >= 60.0 {
            "Sleepy — settling down soon"
        } else if self.needs[3] >= 60.0 {
            "Bored — let's play!"
        } else if self.needs[4] >= 60.0 {
            "Lonely — a little cuddle?"
        } else if self.happiness() <= 65.0 {
            "Doing okay"
        } else {
            "Happy to see you"
        };
        let animation = if self.paused {
            if sleeping { "sleep" } else { "idle" }
        } else if !self.animation.is_empty() {
            self.animation.as_str()
        } else if self.sleeping {
            "sleep"
        } else {
            "idle"
        };
        let sprite_anim = match animation {
            "eat" | "sleep" => animation,
            "play" if self.stage() != "baby" && self.stage() != "egg" => "walk",
            _ => "idle",
        };
        serde_json::json!({
            "ready": true, "generation": self.generation, "form": self.form,
            "stage": self.stage(), "form_label": self.form_label(),
            "age": format!("{}h {}m active", self.age_minutes / 60, self.age_minutes % 60),
            "care": self.care_average().round(), "needs": self.needs.map(|n| n.round()),
            "paused": self.paused,
            "sleeping": sleeping, "mood": mood, "animation": animation,
            "sprite": format!("{}_{}", self.form, sprite_anim),
            "icon": format!("{}_{}_a.png", self.form, if sleeping { "sleep" } else { "idle" }),
            "notice": self.notice,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn minutes(p: &mut State, n: u32) {
        for _ in 0..n {
            p.minute();
        }
    }
    fn child() -> State {
        State {
            form: "child".into(),
            age_minutes: 70,
            ..State::default()
        }
    }
    #[test]
    fn work_day_freezes_nights_and_weekends_without_catchup() {
        let mut p = child();
        p.work_day = true;
        p.advance_scheduled("run", 0, 5, 1078);
        p.advance_scheduled("run", 60_000, 5, 1079);
        let before = (
            p.age_minutes,
            p.needs,
            p.care_sum,
            p.care_count,
            p.remainder_ms,
        );
        for (now, day, minute) in [
            (90_000, 5, 1080),
            (120_000, 6, 600),
            (150_000, 0, 600),
            (180_000, 1, 539),
        ] {
            p.advance_scheduled("run", now, day, minute);
            assert!(p.paused);
            assert_eq!(
                before,
                (
                    p.age_minutes,
                    p.needs,
                    p.care_sum,
                    p.care_count,
                    p.remainder_ms
                )
            );
            assert_eq!(p.snapshot()["animation"], "sleep");
            assert!(p.action("feed", now).is_err());
            p.validate().unwrap();
        }
        p.advance_scheduled("run", 210_000, 1, 540);
        assert!(!p.paused);
        assert_eq!(p.age_minutes, before.0);
        p.advance_scheduled("run", 270_000, 1, 541);
        assert_eq!(p.age_minutes, before.0 + 1);
        p.action("feed", 270_000).unwrap();
    }
    #[test]
    fn work_day_defaults_toggle_eggs_and_generations() {
        let mut old = serde_json::to_value(State::default()).unwrap();
        old.as_object_mut().unwrap().remove("work_day");
        old.as_object_mut().unwrap().remove("paused");
        let mut p: State = serde_json::from_value(old).unwrap();
        assert!(!p.work_day);
        p.advance_scheduled("run", 0, 0, 0);
        p.advance_scheduled("run", 60_000, 0, 1);
        assert_eq!(p.age_minutes, 1);
        assert!(p.action("work-day on", 60_000).is_err());
        p.work_day = true;
        p.advance_scheduled("run", 60_000, 0, 1);
        assert!(p.paused);
        assert_eq!(p.snapshot()["icon"], "egg_idle_a.png");
        p.validate().unwrap();
        assert!(p.action("work-day off", 60_000).is_err());
        p.work_day = false;
        p.advance_scheduled("run", 60_000, 0, 1);
        p.advance_scheduled("run", 120_000, 0, 2);
        assert_eq!(p.age_minutes, 2);
        let mut adult = State {
            form: "adult_gremlin".into(),
            age_minutes: 1510,
            work_day: true,
            paused: true,
            ..State::default()
        };
        adult.action("farewell 1", 0).unwrap();
        assert!(adult.work_day && adult.paused);
        adult.validate().unwrap();
        let saved = serde_json::to_string(&adult).unwrap();
        let restored: State = serde_json::from_str(&saved).unwrap();
        assert!(restored.work_day && restored.paused);
    }
    #[test]
    fn growth_and_generation() {
        let mut p = State::default();
        minutes(&mut p, 4);
        assert_eq!(p.form, "egg");
        minutes(&mut p, 1);
        assert_eq!(p.form, "baby");
        minutes(&mut p, 65);
        assert_eq!(p.form, "child");
        for _ in 70..1510 {
            p.needs = [0.0; 5];
            p.minute();
        }
        assert_eq!(p.form, "adult_ace");
        assert_eq!(p.care_count, 0);
        p.validate().unwrap();
        p.action("farewell 1", 77).unwrap();
        assert_eq!(p.generation, 2);
        assert_eq!(p.form, "egg");
        assert!(p.action("farewell 1", 78).is_err());
        assert_eq!(p.needs, [0.0; 5]);
    }
    #[test]
    fn poor_care_and_scruffy_ceiling() {
        let mut p = child();
        p.needs = [100.0; 5];
        minutes(&mut p, 480);
        assert_eq!(p.form, "teen_scruffy");
        for _ in 0..960 {
            p.needs = [0.0; 5];
            p.minute();
        }
        assert_eq!(p.form, "adult_ok");
        let mut p = child();
        p.needs = [100.0; 5];
        minutes(&mut p, 1440);
        assert_eq!(p.form, "adult_gremlin");
    }
    #[test]
    fn no_offline_aging_and_no_double_tick() {
        let mut p = State::default();
        p.advance("run1", 1_000);
        p.advance("run1", 31_000);
        p.advance("run1", 61_000);
        assert_eq!(p.age_minutes, 1);
        p.advance("run1", 61_000);
        assert_eq!(p.age_minutes, 1);
        p.advance("run2", 900_000);
        assert_eq!(p.age_minutes, 1);
        p.advance("run2", 2_000_000);
        assert_eq!(p.age_minutes, 1);
        p.advance("run2", 0);
        assert_eq!(p.age_minutes, 1);
        p.advance("run2", 60_000);
        assert_eq!(p.age_minutes, 2);
    }
    #[test]
    fn actions_sleep_and_validation() {
        let mut p = child();
        p.needs = [80.0; 5];
        p.sleeping = true;
        p.action("feed", 0).unwrap();
        assert!(!p.sleeping);
        assert_eq!(p.needs[0], 45.0);
        p.action("wash 20", 0).unwrap();
        assert_eq!(p.needs[1], 60.0);
        p.action("pet", 0).unwrap();
        assert_eq!(p.needs[4], 70.0);
        p.action("play", 0).unwrap();
        assert_eq!(p.needs[3], 55.0);
        p.minute();
        assert!(p.sleeping);
        let tired = p.needs[2];
        p.minute();
        assert!(p.needs[2] < tired);
        for bad in ["wash NaN", "wash -1", "wash 26", "farewell 1", "shell"] {
            assert!(p.action(bad, 0).is_err());
        }
        p.validate().unwrap();
        p.needs[0] = f64::NAN;
        assert!(p.validate().is_err());
        let mut p = State::default();
        assert!(p.action("feed", 0).is_err());
        p.form = "../../bad".into();
        assert!(p.validate().is_err());
    }
    #[test]
    fn every_snapshot_has_existing_sprite_names() {
        for form in [
            "egg",
            "baby",
            "child",
            "teen_neat",
            "teen_scruffy",
            "adult_ace",
            "adult_ok",
            "adult_gremlin",
        ] {
            let mut p = State {
                form: form.into(),
                ..State::default()
            };
            for anim in ["", "eat", "wash", "pet", "play", "sleep"] {
                if form == "egg" && anim == "sleep" {
                    continue;
                }
                p.animation = anim.into();
                if form == "egg" && anim == "eat" {
                    continue;
                }
                let snapshot = p.snapshot();
                let sprite = snapshot["sprite"].as_str().unwrap();
                for frame in ["a", "b"] {
                    assert!(
                        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                            .join(format!("../assets/sprites/{sprite}_{frame}.png"))
                            .exists(),
                        "{sprite}"
                    );
                }
            }
        }
    }
}
