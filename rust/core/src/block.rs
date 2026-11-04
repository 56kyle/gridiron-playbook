use crate::document::{Point, Route};
use crate::error::{Error, Result};

pub const BLOCK_TOLERANCE_CM: f64 = 0.1;
pub const CENTIMETERS_PER_YARD: f64 = 91.44;

pub fn offsets() -> [(f64, f64); 28] {
    let mut output = [(0., 0.); 28];
    let mut side = -137.16;
    for row in 0..13 {
        let depth = 114.3 * (row as f64 / 12. - 0.5);
        output[row * 2] = (side, depth);
        side = -side;
        output[row * 2 + 1] = (side, depth);
    }
    output[26] = (side, 0.);
    output
}

pub fn ends_with_block(points: &[Point]) -> bool {
    if points.len() < 29 {
        return false;
    }
    let center = &points[points.len() - 1];
    if &points[points.len() - 29] != center || !center.z.is_finite() {
        return false;
    }
    let side_x = (points[points.len() - 2].x - center.x) / 137.16;
    let side_y = (points[points.len() - 2].y - center.y) / 137.16;
    if (side_x.hypot(side_y) - 1.).abs() * 137.16 > BLOCK_TOLERANCE_CM {
        return false;
    }
    points[points.len() - 28..]
        .iter()
        .zip(offsets())
        .all(|(point, (side, depth))| {
            point.z == center.z
                && ((point.x - center.x) - (side * side_x + depth * side_y))
                    .hypot((point.y - center.y) - (side * side_y - depth * side_x))
                    <= BLOCK_TOLERANCE_CM
        })
}

pub fn block_waypoints(
    points: &[Point],
    index: usize,
    start: Option<(f64, f64)>,
) -> Result<Vec<Point>> {
    let center = points.get(index).ok_or_else(|| {
        Error::new(
            "invalid_index",
            "Choose an existing route point for the block.",
        )
    })?;
    let origin = points[..index]
        .iter()
        .rev()
        .find(|point| point.x != center.x || point.y != center.y)
        .map(|point| (point.x, point.y))
        .or(start.filter(|&(x, y)| (x, y) != (center.x, center.y)));
    let (dx, dy) = if let Some((x, y)) = origin {
        (center.x - x, center.y - y)
    } else if let Some(next) = points[index + 1..]
        .iter()
        .find(|point| point.x != center.x || point.y != center.y)
    {
        (next.x - center.x, next.y - center.y)
    } else {
        (1., 0.)
    };
    let length = dx.hypot(dy);
    if !length.is_finite() || length == 0. {
        return Err(Error::new(
            "invalid_geometry",
            "The block direction exceeds the numeric range.",
        ));
    }
    let (forward_x, forward_y) = (dx / length, dy / length);
    let mut stamp: Vec<_> = offsets()[..27]
        .iter()
        .map(|&(side, depth)| Point {
            x: center.x + (depth * forward_x - side * forward_y),
            y: center.y + (depth * forward_y + side * forward_x),
            z: center.z,
        })
        .collect();
    stamp.push(center.clone());
    let mut check = vec![center.clone()];
    check.extend(stamp.iter().cloned());
    if !ends_with_block(&check) {
        return Err(Error::new(
            "invalid_geometry",
            "The coordinates do not have enough precision to draw a block.",
        ));
    }
    Ok(stamp)
}

pub fn route_yards_without_blocks(route: &Route, start: Option<(f64, f64)>) -> f64 {
    let mut path = Vec::new();
    for point in &route.points {
        path.push(point.clone());
        if ends_with_block(&path) {
            path.truncate(path.len() - 28);
        }
    }
    let mut previous = start;
    let mut yards = 0.;
    for point in path {
        if let Some((x, y)) = previous {
            yards += (point.x - x).hypot(point.y - y) / CENTIMETERS_PER_YARD;
        }
        previous = Some((point.x, point.y));
    }
    yards
}
