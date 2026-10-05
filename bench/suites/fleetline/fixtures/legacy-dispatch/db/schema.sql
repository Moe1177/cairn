CREATE TABLE legacy_trips (trip_ref varchar(32) PRIMARY KEY, driver_ref varchar(32), status varchar(16));
CREATE TABLE legacy_drivers (driver_ref varchar(32) PRIMARY KEY, license_number varchar(32));
