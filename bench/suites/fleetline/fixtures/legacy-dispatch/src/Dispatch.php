<?php
// Assigns the nearest legacy driver to a trip.
function assign_trip($tripRef) {
    return "SELECT driver_ref, license_number FROM legacy_drivers LIMIT 1";
}
