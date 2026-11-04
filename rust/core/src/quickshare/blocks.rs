use crate::block::{ends_with_block, offsets};
use crate::document::Point;

pub(super) const BLOCK_POINTS: usize = 28;
const UNIT_TOLERANCE: f64 = 1e-12;
const ANGLE_STEP: f64 = std::f64::consts::TAU / 65536.0;
const SWEEP_TOLERANCE: f64 = 0.4;

pub(super) type Direction = (f64, f64);

#[derive(Clone, Copy, Debug)]
pub(super) struct RouteBlock {
    pub anchor: usize,
    pub direction: Direction,
}

pub(super) fn valid_direction(direction: Direction) -> bool {
    (direction.0.hypot(direction.1) - 1.0).abs() <= UNIT_TOLERANCE
}

pub(super) fn compact_heading(direction: Direction) -> u16 {
    (direction.1.atan2(direction.0) / ANGLE_STEP)
        .round_ties_even()
        .rem_euclid(65536.0) as u16
}

pub(super) fn heading_direction(heading: u16) -> Direction {
    let angle = f64::from(heading) * ANGLE_STEP;
    (angle.cos(), angle.sin())
}

pub(super) fn inferred_direction(points: &[Point], anchor: usize) -> Option<Direction> {
    let previous = anchor.checked_sub(1).and_then(|index| points.get(index))?;
    let point = points.get(anchor)?;
    let dx = point.x - previous.x;
    let dy = point.y - previous.y;
    // This arithmetic order is part of the v2 format, shared by the Python and JS decoders.
    let length = (dx * dx + dy * dy).sqrt();
    if length == 0.0 || !length.is_finite() {
        return None;
    }
    let direction = (dx / length, dy / length);
    valid_direction(direction).then_some(direction)
}

pub(super) fn coordinates(anchor: &Point, direction: Direction) -> Vec<Point> {
    let (ux, uy) = direction;
    let mut result: Vec<Point> = offsets()[..BLOCK_POINTS - 1]
        .iter()
        .map(|&(side, depth)| Point {
            x: anchor.x + (depth * ux - side * uy),
            y: anchor.y + (depth * uy + side * ux),
            z: anchor.z,
        })
        .collect();
    result.push(anchor.clone());
    result
}

pub(super) fn expand_blocks(points: &[Point], blocks: &[RouteBlock]) -> Vec<Point> {
    let mut expanded = Vec::with_capacity(points.len() + blocks.len() * BLOCK_POINTS);
    let mut block_index = 0;
    for (index, point) in points.iter().enumerate() {
        expanded.push(point.clone());
        while block_index < blocks.len() && blocks[block_index].anchor == index {
            expanded.extend(coordinates(point, blocks[block_index].direction));
            block_index += 1;
        }
    }
    expanded
}

fn candidate_directions(
    points: &[Point],
    index: usize,
    previous: Option<(f64, f64)>,
) -> Vec<Direction> {
    let center = &points[index];
    let mut approach = (1.0, 0.0);
    if let Some(before) = previous.filter(|before| *before != (center.x, center.y)) {
        approach = (center.x - before.0, center.y - before.1);
    } else if let Some(after) = points[index + BLOCK_POINTS + 1..]
        .iter()
        .find(|point| (point.x, point.y) != (center.x, center.y))
    {
        approach = (after.x - center.x, after.y - center.y);
    }
    let mut candidates = Vec::with_capacity(3);
    let length = approach.0.hypot(approach.1);
    if length != 0.0 && length.is_finite() {
        candidates.push((approach.0 / length, approach.1 / length));
    }
    let side = offsets()[BLOCK_POINTS - 2].0;
    let edge = &points[index + BLOCK_POINTS - 1];
    let measured = ((edge.y - center.y) / side, (center.x - edge.x) / side);
    candidates.push(measured);
    candidates.push(heading_direction(compact_heading(measured)));
    candidates
}

fn matching_direction(
    points: &[Point],
    index: usize,
    previous: Option<(f64, f64)>,
) -> Option<Direction> {
    let end = index + BLOCK_POINTS;
    if end >= points.len() || points[end] != points[index] || !ends_with_block(&points[index..=end])
    {
        return None;
    }
    candidate_directions(points, index, previous)
        .into_iter()
        .find(|&direction| {
            valid_direction(direction)
                && coordinates(&points[index], direction)
                    .iter()
                    .zip(&points[index + 1..=end])
                    .all(|(generated, stored)| {
                        generated.x.to_bits() == stored.x.to_bits()
                            && generated.y.to_bits() == stored.y.to_bits()
                            && generated.z.to_bits() == stored.z.to_bits()
                    })
        })
}

pub(super) fn split_blocks(
    points: &[Point],
    start: Option<(f64, f64)>,
) -> (Vec<Point>, Vec<RouteBlock>) {
    let mut literals = Vec::new();
    let mut blocks = Vec::new();
    let mut previous = start;
    let mut index = 0;
    while index < points.len() {
        let current = &points[index];
        if index > 0 {
            let prior = &points[index - 1];
            if (prior.x, prior.y) != (current.x, current.y) {
                previous = Some((prior.x, prior.y));
            }
        }
        literals.push(current.clone());
        while let Some(direction) = matching_direction(points, index, previous) {
            blocks.push(RouteBlock {
                anchor: literals.len() - 1,
                direction,
            });
            index += BLOCK_POINTS;
            let edge = &points[index - 1];
            previous = Some((edge.x, edge.y));
        }
        index += 1;
    }
    (literals, blocks)
}

pub(super) fn has_block_strokes(points: &[Point]) -> bool {
    let pattern = offsets();
    let width = pattern[1].0 - pattern[0].0;
    let step = pattern[2].1 - pattern[1].1;
    points.windows(4).any(|span| {
        let (a, b, c, d) = (&span[0], &span[1], &span[2], &span[3]);
        let (ux, uy) = (b.x - a.x, b.y - a.y);
        if (ux.hypot(uy) - width).abs() > SWEEP_TOLERANCE {
            return false;
        }
        let (gap_x, gap_y) = (c.x - b.x, c.y - b.y);
        if (gap_x.hypot(gap_y) - step).abs() > SWEEP_TOLERANCE {
            return false;
        }
        let along_sweep = (gap_x * ux + gap_y * uy) / width;
        let reverse_error = ((d.x - c.x) + ux).hypot((d.y - c.y) + uy);
        along_sweep.abs() <= SWEEP_TOLERANCE && reverse_error <= SWEEP_TOLERANCE
    })
}
