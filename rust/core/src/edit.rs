use crate::document::{self, Play, Point};
use crate::error::{Error, Result};
use crate::{block, formation};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Clone, Copy, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(deny_unknown_fields)]
struct PointSelection {
    route_index: usize,
    point_index: usize,
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
enum Edit {
    CreatePlay {
        formation_name: String,
        play_name: String,
    },
    DuplicatePlay {
        play_index: usize,
        play_name: String,
    },
    RenamePlay {
        play_index: usize,
        play_name: String,
    },
    ChangeFormation {
        play_index: usize,
        formation_name: String,
    },
    DeletePlays {
        indices: Vec<usize>,
    },
    ReorderPlays {
        indices: Vec<usize>,
        insertion: usize,
    },
    AddRoute {
        play_index: usize,
        slot: u8,
        points: Vec<Point>,
    },
    MovePoint {
        play_index: usize,
        route_index: usize,
        point_index: usize,
        x: f64,
        y: f64,
    },
    MovePoints {
        play_index: usize,
        points: Vec<PointSelection>,
        dx: f64,
        dy: f64,
    },
    DeletePoints {
        play_index: usize,
        points: Vec<PointSelection>,
    },
    InsertPoint {
        play_index: usize,
        route_index: usize,
        point_index: usize,
        x: f64,
        y: f64,
    },
    DeletePoint {
        play_index: usize,
        route_index: usize,
        point_index: usize,
    },
    AddBlock {
        play_index: usize,
        route_index: usize,
        point_index: usize,
    },
    DeleteRoute {
        play_index: usize,
        route_index: usize,
    },
    FlipPlay {
        play_index: usize,
    },
    ClearRoutes {
        play_index: usize,
    },
}

fn invalid_index() -> Error {
    Error::new(
        "invalid_index",
        "The selected play, route, or point is no longer available.",
    )
}

fn name(value: &str) -> Result<String> {
    let value = value.trim();
    if value.is_empty() {
        return Err(Error::new("invalid_name", "Enter a name."));
    }
    document::validate_name(value)?;
    Ok(value.into())
}

pub fn selection(indices: &[usize], length: usize) -> Result<Vec<usize>> {
    if indices.is_empty() {
        return Err(Error::new("invalid_selection", "Select at least one play."));
    }
    let mut sorted = indices.to_vec();
    sorted.sort_unstable();
    if sorted.iter().any(|&index| index >= length) {
        return Err(invalid_index());
    }
    if sorted.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(Error::new(
            "invalid_selection",
            "Select each play only once.",
        ));
    }
    Ok(sorted)
}

fn routes_mut(play: &mut Value) -> Result<&mut Vec<Value>> {
    play.get_mut("Routes_0")
        .and_then(Value::as_array_mut)
        .ok_or_else(invalid_index)
}

fn points_mut(play: &mut Value, route_index: usize) -> Result<&mut Vec<Value>> {
    routes_mut(play)?
        .get_mut(route_index)
        .and_then(|route| route.get_mut("Points_0"))
        .and_then(Value::as_array_mut)
        .ok_or_else(invalid_index)
}

fn update_point(point: &mut Value, x: f64, y: f64) -> Result<()> {
    let original = document::point_from_raw(point)?;
    document::validate_point(&Point {
        x,
        y,
        z: original.z,
    })?;
    point["X_0"] = json!(x);
    point["Y_0"] = json!(y);
    Ok(())
}

fn selected_points(mut points: Vec<PointSelection>, play: &Play) -> Result<Vec<PointSelection>> {
    if points.is_empty() {
        return Err(Error::new("invalid_selection", "Select at least one node."));
    }
    points.sort_unstable();
    if points.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(Error::new(
            "invalid_selection",
            "Select each node only once.",
        ));
    }
    for point in &points {
        play.routes
            .get(point.route_index)
            .and_then(|route| route.points.get(point.point_index))
            .ok_or_else(invalid_index)?;
    }
    Ok(points)
}

fn delete_points(play: &mut Value, normalized: &Play, points: Vec<PointSelection>) -> Result<()> {
    let selected = selected_points(points, normalized)?;
    let mut counts = vec![0; normalized.routes.len()];
    for point in &selected {
        counts[point.route_index] += 1;
    }
    for (route_index, &count) in counts.iter().enumerate().filter(|(_, count)| **count > 0) {
        let route = &normalized.routes[route_index];
        let remaining = route.points.len() - count;
        if remaining == 1 && formation::start(&normalized.formation_name, route.slot).is_none() {
            return Err(Error::new(
                "invalid_geometry",
                "A route without a known starting position needs two nodes. Select all its nodes to delete the route.",
            ));
        }
    }
    for point in selected.into_iter().rev() {
        points_mut(play, point.route_index)?.remove(point.point_index);
    }
    for (route_index, &count) in counts.iter().enumerate().rev() {
        if count > 0 && count == normalized.routes[route_index].points.len() {
            routes_mut(play)?.remove(route_index);
        }
    }
    Ok(())
}

fn mutate_play(play: &mut Value, edit: Edit) -> Result<()> {
    let normalized = document::play_from_raw(play)?;
    match edit {
        Edit::RenamePlay { play_name, .. } => play["PlayName_0"] = json!(name(&play_name)?),
        Edit::ChangeFormation { formation_name, .. } => {
            play["FormationName_0"] = json!(name(&formation_name)?)
        }
        Edit::AddRoute { slot, points, .. } => {
            let minimum = if formation::start(&normalized.formation_name, slot).is_some() {
                1
            } else {
                2
            };
            if points.len() < minimum {
                return Err(Error::new(
                    "invalid_geometry",
                    "Draw enough waypoints to form a route.",
                ));
            }
            for point in &points {
                document::validate_point(point)?;
            }
            routes_mut(play)?.push(json!({"Slot_0":slot,"Points_0":points.iter().map(document::point_to_raw).collect::<Vec<_>>()}));
        }
        Edit::MovePoint {
            route_index,
            point_index,
            x,
            y,
            ..
        } => {
            let point = points_mut(play, route_index)?
                .get_mut(point_index)
                .ok_or_else(invalid_index)?;
            update_point(point, x, y)?;
        }
        Edit::MovePoints { points, dx, dy, .. } => {
            let selected = selected_points(points, &normalized)?;
            for selected in selected {
                let original =
                    &normalized.routes[selected.route_index].points[selected.point_index];
                let point = &mut points_mut(play, selected.route_index)?[selected.point_index];
                update_point(
                    point,
                    if dx == 0.0 {
                        original.x
                    } else {
                        original.x + dx
                    },
                    if dy == 0.0 {
                        original.y
                    } else {
                        original.y + dy
                    },
                )?;
            }
        }
        Edit::DeletePoints { points, .. } => delete_points(play, &normalized, points)?,
        Edit::InsertPoint {
            route_index,
            point_index,
            x,
            y,
            ..
        } => {
            let route = normalized
                .routes
                .get(route_index)
                .ok_or_else(invalid_index)?;
            if point_index > route.points.len() {
                return Err(invalid_index());
            }
            let z = if route.points.is_empty() {
                0.
            } else if point_index == 0 {
                route.points[0].z
            } else if point_index == route.points.len() {
                route.points[point_index - 1].z
            } else {
                let previous = &route.points[point_index - 1];
                let following = &route.points[point_index];
                let dx = following.x - previous.x;
                let dy = following.y - previous.y;
                let length = dx.hypot(dy);
                if length == 0. {
                    previous.z
                } else {
                    let projection =
                        (x - previous.x) * (dx / length) + (y - previous.y) * (dy / length);
                    let fraction = (projection / length).clamp(0., 1.);
                    (1. - fraction) * previous.z + fraction * following.z
                }
            };
            let point = Point { x, y, z };
            document::validate_point(&point)?;
            points_mut(play, route_index)?.insert(point_index, document::point_to_raw(&point));
        }
        Edit::DeletePoint {
            route_index,
            point_index,
            ..
        } => {
            let route = normalized
                .routes
                .get(route_index)
                .ok_or_else(invalid_index)?;
            if point_index >= route.points.len() {
                return Err(invalid_index());
            }
            let minimum = if formation::start(&normalized.formation_name, route.slot).is_some() {
                1
            } else {
                2
            };
            if route.points.len() <= minimum {
                return Err(Error::new(
                    "invalid_geometry",
                    "The route needs its remaining waypoints.",
                ));
            }
            points_mut(play, route_index)?.remove(point_index);
        }
        Edit::AddBlock {
            route_index,
            point_index,
            ..
        } => {
            let route = normalized
                .routes
                .get(route_index)
                .ok_or_else(invalid_index)?;
            let stamp = block::block_waypoints(
                &route.points,
                point_index,
                formation::start(&normalized.formation_name, route.slot),
            )?;
            let points = points_mut(play, route_index)?;
            let mut raw_stamp: Vec<_> = stamp.iter().map(document::point_to_raw).collect();
            raw_stamp[27] = points[point_index].clone();
            points.splice(point_index + 1..point_index + 1, raw_stamp);
        }
        Edit::DeleteRoute { route_index, .. } => {
            let routes = routes_mut(play)?;
            if route_index >= routes.len() {
                return Err(invalid_index());
            }
            routes.remove(route_index);
        }
        Edit::ClearRoutes { .. } => routes_mut(play)?.clear(),
        Edit::FlipPlay { .. } => {
            play["FormationName_0"] = json!(formation::mirrored_name(&normalized.formation_name));
            for (index, route) in routes_mut(play)?.iter_mut().enumerate() {
                let slot = normalized.routes[index].slot;
                route["Slot_0"] = json!(match slot {
                    2 => 3,
                    3 => 2,
                    5 => 6,
                    6 => 5,
                    other => other,
                });
                for point in route["Points_0"].as_array_mut().ok_or_else(invalid_index)? {
                    let y = document::point_from_raw(point)?.y;
                    point["Y_0"] = json!(-y);
                }
            }
        }
        _ => {
            return Err(Error::new(
                "invalid_command",
                "The command does not edit an existing play.",
            ))
        }
    }
    Ok(())
}

pub fn apply_edit(text: &str, command_json: &str) -> Result<String> {
    if command_json.len() > document::MAX_SAVE_BYTES {
        return Err(Error::new(
            "capacity",
            "The edit command exceeds the document limit.",
        ));
    }
    let command: Edit = serde_json::from_str(command_json)
        .map_err(|error| Error::new("invalid_command", error.to_string()))?;
    let mut document = document::parse_document(text)?;
    let before = serde_json::to_string(&document)?;
    let mut plays = document::plays(&document)?.clone();
    match command {
        Edit::CreatePlay {
            formation_name,
            play_name,
        } => plays.insert(
            0,
            document::play_to_raw(&Play {
                formation_name: name(&formation_name)?,
                play_name: name(&play_name)?,
                routes: vec![],
            }),
        ),
        Edit::DuplicatePlay {
            play_index,
            play_name,
        } => {
            let mut duplicate = plays.get(play_index).ok_or_else(invalid_index)?.clone();
            duplicate["PlayName_0"] = json!(name(&play_name)?);
            plays.insert(0, duplicate);
        }
        Edit::DeletePlays { indices } => {
            let indices = selection(&indices, plays.len())?;
            for index in indices.into_iter().rev() {
                plays.remove(index);
            }
        }
        Edit::ReorderPlays { indices, insertion } => {
            let indices = selection(&indices, plays.len())?;
            if insertion > plays.len() {
                return Err(invalid_index());
            }
            let chosen: Vec<_> = indices.iter().map(|&index| plays[index].clone()).collect();
            let destination =
                insertion - indices.iter().filter(|&&index| index < insertion).count();
            for &index in indices.iter().rev() {
                plays.remove(index);
            }
            plays.splice(destination..destination, chosen);
        }
        other => {
            let play_index = match &other {
                Edit::RenamePlay { play_index, .. }
                | Edit::ChangeFormation { play_index, .. }
                | Edit::AddRoute { play_index, .. }
                | Edit::MovePoint { play_index, .. }
                | Edit::MovePoints { play_index, .. }
                | Edit::DeletePoints { play_index, .. }
                | Edit::InsertPoint { play_index, .. }
                | Edit::DeletePoint { play_index, .. }
                | Edit::AddBlock { play_index, .. }
                | Edit::DeleteRoute { play_index, .. }
                | Edit::FlipPlay { play_index }
                | Edit::ClearRoutes { play_index } => *play_index,
                _ => unreachable!(),
            };
            mutate_play(plays.get_mut(play_index).ok_or_else(invalid_index)?, other)?;
        }
    }
    document::replace_plays(&mut document, plays)?;
    let after = document::serialize_document(&document)?;
    Ok(if before == after {
        text.to_owned()
    } else {
        after
    })
}

pub fn transfer_plays(
    source: &str,
    target: &str,
    indices_json: &str,
    insertion: usize,
    mode: &str,
) -> Result<String> {
    if !matches!(mode, "copy" | "move") {
        return Err(Error::new("invalid_command", "Choose copy or move."));
    }
    let mut source_doc = document::parse_document(source)?;
    let mut target_doc = document::parse_document(target)?;
    let mut source_plays = document::plays(&source_doc)?.clone();
    let mut target_plays = document::plays(&target_doc)?.clone();
    let indices: Vec<usize> = serde_json::from_str(indices_json)?;
    let selected = selection(&indices, source_plays.len())?;
    if insertion > target_plays.len() {
        return Err(invalid_index());
    }
    let copied: Vec<_> = selected
        .iter()
        .map(|&index| source_plays[index].clone())
        .collect();
    target_plays.splice(insertion..insertion, copied);
    document::replace_plays(&mut target_doc, target_plays)?;
    let target_result = document::serialize_document(&target_doc)?;
    let source_result = if mode == "move" {
        for index in selected.into_iter().rev() {
            source_plays.remove(index);
        }
        document::replace_plays(&mut source_doc, source_plays)?;
        document::serialize_document(&source_doc)?
    } else {
        source.to_owned()
    };
    Ok(serde_json::to_string(
        &json!({"source":source_result,"target":target_result}),
    )?)
}
