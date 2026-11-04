use serde::Serialize;

pub const FORMATION_NAMES: [&str; 10] = [
    "Twins Right",
    "Twins Left",
    "Singleback Deuce",
    "Shotgun Right",
    "Shotgun Left",
    "I-Wing Right",
    "I-Wing Left",
    "Goal Line",
    "Bunch Right",
    "Bunch Left",
];

#[derive(Serialize)]
pub struct Position {
    pub slot: u8,
    pub label: &'static str,
    pub x: f64,
    pub y: f64,
}

#[derive(Serialize)]
pub struct Formation {
    pub name: &'static str,
    pub positions: Vec<Position>,
}

pub fn start(name: &str, slot: u8) -> Option<(f64, f64)> {
    let (qb, rb, right, left) = match name {
        "Twins Right" => (-600., (-50., 1050.), (-50., 1650.), (-50., -1350.)),
        "Twins Left" => (-600., (-50., -1050.), (-50., 1400.), (-50., -1650.)),
        "Singleback Deuce" => (-400., (-650., 0.), (-50., 1700.), (-50., -1700.)),
        "Shotgun Right" => (-600., (-550., 300.), (-50., 1650.), (-50., -1650.)),
        "Shotgun Left" => (-600., (-550., -300.), (-50., 1650.), (-50., -1650.)),
        "I-Wing Right" => (-400., (-700., 0.), (-150., 700.), (-50., -1650.)),
        "I-Wing Left" => (-400., (-700., 0.), (-50., 1650.), (-150., -700.)),
        "Goal Line" => (-400., (-650., 0.), (-100., 700.), (-100., -700.)),
        "Bunch Right" => (-600., (-200., 1050.), (-50., 1650.), (-50., -1350.)),
        "Bunch Left" => (-600., (-200., -1050.), (-50., 1350.), (-50., -1650.)),
        _ => return None,
    };
    match slot {
        0 => Some((qb, 0.)),
        1 => Some((-50., 0.)),
        2 => Some((-50., -350.)),
        3 => Some((-50., 350.)),
        4 => Some(rb),
        5 => Some(right),
        6 => Some(left),
        _ => None,
    }
}

pub fn formation_data() -> crate::error::Result<String> {
    let labels = ["QB", "C", "LT", "RT", "RB", "WR-R", "WR-L"];
    let formations: Vec<_> = FORMATION_NAMES
        .iter()
        .map(|&name| Formation {
            name,
            positions: labels
                .iter()
                .enumerate()
                .map(|(slot, &label)| {
                    let (x, y) = start(name, slot as u8).expect("Known formation and slot");
                    Position {
                        slot: slot as u8,
                        label,
                        x,
                        y,
                    }
                })
                .collect(),
        })
        .collect();
    Ok(serde_json::to_string(&formations)?)
}

pub fn mirrored_name(name: &str) -> String {
    if let Some(prefix) = name.strip_suffix(" Right") {
        return format!("{prefix} Left");
    }
    if let Some(prefix) = name.strip_suffix(" Left") {
        return format!("{prefix} Right");
    }
    name.into()
}
