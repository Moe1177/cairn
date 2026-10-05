pub fn precision_for_zoom(zoom: u8) -> usize {
    (zoom as usize / 2).clamp(1, 12)
}
