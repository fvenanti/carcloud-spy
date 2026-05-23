"""Buckets canónicos cross-agencia.

Mapea las categorías nativas de cada agencia a buckets comparables, para
poder comparar precio "manzana con manzana" cross-agencia en el dashboard.

Si una categoría nueva aparece y no está mapeada, queda en bucket NULL
(se ve en el dashboard como "Sin bucket") — se agrega manualmente acá.
"""

from __future__ import annotations

# slug → orden para sort en UI + etiqueta legible
BUCKET_META: dict[str, tuple[int, str]] = {
    "mini":               (10, "Mini / Económico chico (MT)"),
    "compacto_mt":        (20, "Compacto 5P (MT)"),
    "compacto_at":        (30, "Compacto / Crossover (AT)"),
    "sedan_medio_mt":     (40, "Sedán medio (MT)"),
    "sedan_medio_at":     (50, "Sedán medio (AT)"),
    "sedan_grande_at":    (60, "Sedán grande (AT)"),
    "suv_compacto_mt":    (70, "SUV compacto (MT)"),
    "suv_compacto_at":    (80, "SUV compacto (AT)"),
    "suv_compacto_4x4":   (85, "SUV compacto 4x4 (AT)"),
    "suv_mediano_4x4":    (90, "SUV mediano 4x4 (AT) — Compass / CRV / Corolla Cross"),
    "suv_prestige_4x4":   (95, "SUV prestige 4x4 (AT) — Territory / Bronco"),
    "familiar_7pax":      (100, "Familiar / 7 pasajeros (AT)"),
    "pickup_4x4_mt":      (110, "Pickup 4x4 (MT)"),
    "pickup_4x4_at":      (120, "Pickup 4x4 (AT)"),
    "van_8_10pax":        (130, "Van familiar 8-10 pax"),
    "van_12pax":          (140, "Van 12 pax"),
    "van_14pax":          (145, "Van 14 pax"),
    "premium_ultra":      (150, "Premium ultra ($3M+)"),
}


# Mapping (agencia_slug, categoria) → bucket
# Las categorías son las que vienen del adapter (strings exactos como se ven en DB).
_MAPPING: dict[str, dict[str, str]] = {
    "aba": {
        "C- - 3P AA DA A / AIRBAG / ABS":          "mini",
        "C - 5P AA DA A / AIRBAG / ABS":           "compacto_mt",
        "D- - 4P MD BAUL / AIRBAG / ABS":          "sedan_medio_mt",
        "D - 4P MD BAUL / AIRBAG / ABS":           "sedan_medio_mt",
        "F - 4P GDE / BAUL / AIRBAG / ABS":        "sedan_medio_mt",
        "G - 4P GDE / BAUL / AIRBAG / ABS":        "sedan_medio_at",
        "H - FAM 5 PAX / AIRBAG / ABS":            "sedan_medio_mt",
        # I- es manual: no tiene par AT en Hertz/Tara, queda sin bucket
        "I- - FAM 7 PAX / AIRBAG / ABS":           None,
        "I+ - FAM 7 PAX AT / AIRBAG / ABS":        "familiar_7pax",
        "J - 4X2 MAN / SUV / MEDIANA":             "suv_compacto_mt",
        "K - 4X2 AUTO / SUV / MEDIANA":            "suv_compacto_at",
        "L - 4X4 AUT / SUV / MEDIANA":             "suv_compacto_4x4",
        "L+ - 4X4 / AUT / CON CAJA":               "pickup_4x4_at",
        "M - 4X4 / AUT / SUV / GDE":               "suv_mediano_4x4",
        "M- - 4X4 / AUT / SUV / GDE":              "suv_mediano_4x4",
        "N - VAN / 8 PAX / FULL":                  "van_8_10pax",
        "N-":                                       "van_12pax",
        "N+ - VAN / 12 PAX / FULL":                "van_12pax",
        "O - VAN / 14 PAX / FULL":                 "van_14pax",
    },
    "hertz": {
        "(C) Económico MT":                  "mini",
        "(H) Compacto MT":                   "compacto_mt",
        "(H1) Sedan Intermedio MT":          "sedan_medio_mt",
        "(H2) Sedan Intermedio Plus MT":     "sedan_medio_mt",
        "(H3) Sedan Intermedio Plus MT":     "sedan_medio_mt",
        "(W) Sedan Intermedio Manual":       "sedan_medio_mt",
        "(K1) Compacto AT":                  "compacto_at",
        "(P) Compacto AT":                   "compacto_at",
        "(W1) Compacto Intermedio Plus AT":  "compacto_at",
        "(K) Sedan Intermedio AT":           "sedan_medio_at",
        "(W2) Sedan Intermedio Plus AT":     "sedan_grande_at",
        "(W3) Sedan Intermedio Plus AT":     "sedan_grande_at",
        "(Z) Sedan Grande AT":               "sedan_grande_at",
        "(N) SUV Compacto MT":               "suv_compacto_mt",
        "(N1) SUV Compacto AT":              "suv_compacto_at",
        "(M) SUV Intermedio Plus AT":        "suv_compacto_4x4",
        "(S) SUV Intermedio AT":             "suv_mediano_4x4",
        "(T1) SUV Prestige":                 "suv_mediano_4x4",
        "(T) SUV Prestige":                  "suv_prestige_4x4",
        "(I) SUV Economico AT 7 Pax":        "familiar_7pax",
        "(J) Camioneta 4X4 MT":              "pickup_4x4_mt",
        "(J1) Camioneta 4X4 AT":             "pickup_4x4_at",
        "(R) SUV Prestige 4X4":              "premium_ultra",
        "(XX) Camioneta Premium":            "premium_ultra",
    },
    "taraborelli": {
        "Mini":                                            "mini",
        "Compacto MT":                                     "compacto_mt",
        "Compacto AT":                                     "compacto_at",
        "Crossover MT":                                    "compacto_at",
        "Crossover AT":                                    "sedan_medio_at",
        "Sedan Económico MT":                              "sedan_medio_mt",
        "Sedan Económico AT":                              "sedan_medio_at",
        "Sedan Intermedio AT":                             "sedan_grande_at",
        "SUV Economico MT 4x4":                            "suv_compacto_mt",
        "SUV Economico AT":                                "suv_compacto_at",
        "SUV Economico 7 Pax AT":                          "familiar_7pax",
        "SUV Intermedio AT":                               "suv_mediano_4x4",
        "SUV Intermedio Elite AT":                         "suv_prestige_4x4",
        "Pick up 4x4 MT":                                  "pickup_4x4_mt",
        "Pick up 4x4 AT":                                  "pickup_4x4_at",
        "Pick Up Compacta 4x4 AT":                         "pickup_4x4_at",
        "Van 9 Pax":                                       "van_8_10pax",
        "Van Premium 9 Pax":                               "van_8_10pax",
        "Sedan Premium":                                   "premium_ultra",
        "Pick up 4x4 lujo grande AT":                      "premium_ultra",
        "SUV Premium":                                     "premium_ultra",
        # Sin bucket directo (fuera del paradigma "auto turismo"):
        # "Furgón Urbano - Fletes y Paquetería - Servicios": None,
    },
}


def get_bucket(agencia_slug: str, categoria: str) -> str | None:
    """Devuelve el bucket canónico o None si no está mapeado."""
    return _MAPPING.get(agencia_slug, {}).get(categoria)


def bucket_label(bucket: str | None) -> str:
    if not bucket:
        return "Sin bucket"
    return BUCKET_META.get(bucket, (999, bucket))[1]


def bucket_order(bucket: str | None) -> int:
    if not bucket:
        return 999
    return BUCKET_META.get(bucket, (999, bucket))[0]


def all_buckets_sorted() -> list[tuple[str, str]]:
    """Lista de (slug, label) ordenada para UI."""
    items = sorted(BUCKET_META.items(), key=lambda kv: kv[1][0])
    return [(slug, meta[1]) for slug, meta in items]
