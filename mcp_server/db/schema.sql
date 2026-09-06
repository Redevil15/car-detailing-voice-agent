-- Esquema mock del negocio de car detailing.
-- Datos 100% sintéticos. Fechas y horas en ISO 8601 (TEXT).

PRAGMA foreign_keys = ON;

-- Catálogo de servicios con su precio. Fuente de verdad de consultar_precio().
CREATE TABLE IF NOT EXISTS servicios (
    id           INTEGER PRIMARY KEY,
    nombre       TEXT    NOT NULL UNIQUE,
    descripcion  TEXT    NOT NULL,
    precio_mxn   INTEGER NOT NULL CHECK (precio_mxn > 0),
    duracion_min INTEGER NOT NULL CHECK (duracion_min > 0),
    activo       INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

-- Clientes. El teléfono es la identidad natural en un flujo por voz.
CREATE TABLE IF NOT EXISTS clientes (
    id       INTEGER PRIMARY KEY,
    nombre   TEXT NOT NULL,
    telefono TEXT NOT NULL UNIQUE
);

-- Capacidad del taller: cuántos autos caben en cada franja horaria.
CREATE TABLE IF NOT EXISTS disponibilidad (
    fecha      TEXT    NOT NULL,
    hora       TEXT    NOT NULL,
    cupo_total INTEGER NOT NULL CHECK (cupo_total >= 0),
    PRIMARY KEY (fecha, hora)
);

-- Citas agendadas. Los cupos libres se derivan: cupo_total - citas confirmadas.
CREATE TABLE IF NOT EXISTS citas (
    id          INTEGER PRIMARY KEY,
    cliente_id  INTEGER NOT NULL REFERENCES clientes(id),
    servicio_id INTEGER NOT NULL REFERENCES servicios(id),
    fecha       TEXT    NOT NULL,
    hora        TEXT    NOT NULL,
    estado      TEXT    NOT NULL DEFAULT 'confirmada'
                CHECK (estado IN ('confirmada', 'cancelada')),
    creado_en   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (fecha, hora) REFERENCES disponibilidad(fecha, hora)
);

CREATE INDEX IF NOT EXISTS idx_citas_fecha ON citas (fecha, hora);
