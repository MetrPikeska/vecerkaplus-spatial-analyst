"""
Testy pro prostorovou analýzu VečerkaPlus.
"""
import os
import warnings
warnings.filterwarnings("ignore")

import json
import pytest
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "output")

FM_LAT, FM_LON = 49.6754886, 18.3389397
CRS_METRIC = "EPSG:5514"
CRS_WGS    = "EPSG:4326"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def test_sldb_loads():
    gdf = gpd.read_file(
        os.path.join(DATA_DIR, "obce_sldb",
                     "csu_geodb_sde_CISOB_obyvatelstvo_etl_20210326.gpkg"),
        rows=10,
    )
    assert len(gdf) > 0
    assert "gis131620000" in gdf.columns  # total population column
    assert gdf.crs is not None


def test_marketing_spots_loads():
    gdf = gpd.read_file(os.path.join(DATA_DIR, "marketing-spots-fm.gpkg"))
    assert len(gdf) > 100
    assert "amenity" in gdf.columns
    assert gdf.crs.to_epsg() == 4326


# ---------------------------------------------------------------------------
# Buffer geometry
# ---------------------------------------------------------------------------

def test_buffer_20km():
    fm = gpd.GeoDataFrame([{"geometry": Point(FM_LON, FM_LAT)}], crs=CRS_WGS)
    fm_m = fm.to_crs(CRS_METRIC)
    buf = fm_m.buffer(20_000)
    area_km2 = buf.area.values[0] / 1e6
    # kruh r=20 km → π·400 ≈ 1256.6 km²; S-JTSK lehce deformuje, tolerance 5 %
    assert abs(area_km2 - 1256.6) / 1256.6 < 0.05, f"Plocha bufferu {area_km2:.1f} km² mimo očekávání"


def test_buffer_contains_fm():
    fm = gpd.GeoDataFrame([{"geometry": Point(FM_LON, FM_LAT)}], crs=CRS_WGS)
    fm_m = fm.to_crs(CRS_METRIC)
    buf = fm_m.buffer(20_000).iloc[0]
    assert fm_m.geometry.iloc[0].within(buf)


# ---------------------------------------------------------------------------
# Spatial join – obce
# ---------------------------------------------------------------------------

def test_obce_in_buffer_count():
    gdf = gpd.read_file(
        os.path.join(DATA_DIR, "obce_sldb",
                     "csu_geodb_sde_CISOB_obyvatelstvo_etl_20210326.gpkg")
    )
    gdf = gdf.rename(columns={"gis131620000": "obyvatelstvo_celkem"})
    fm = gpd.GeoDataFrame([{"geometry": Point(FM_LON, FM_LAT)}], crs=CRS_WGS)
    buf = fm.to_crs(CRS_METRIC).buffer(20_000).iloc[0]
    gdf_m = gdf.to_crs(CRS_METRIC)
    centroids_in = gdf_m.geometry.centroid.within(buf)
    in_buf = gdf_m[centroids_in]
    assert 50 <= len(in_buf) <= 150, f"Počet obcí {len(in_buf)} mimo očekávaný rozsah 50–150"


def test_population_in_buffer():
    gdf = gpd.read_file(
        os.path.join(DATA_DIR, "obce_sldb",
                     "csu_geodb_sde_CISOB_obyvatelstvo_etl_20210326.gpkg")
    )
    gdf = gdf.rename(columns={"gis131620000": "obyvatelstvo_celkem"})
    fm = gpd.GeoDataFrame([{"geometry": Point(FM_LON, FM_LAT)}], crs=CRS_WGS)
    buf = fm.to_crs(CRS_METRIC).buffer(20_000).iloc[0]
    gdf_m = gdf.to_crs(CRS_METRIC)
    in_buf = gdf_m[gdf_m.geometry.centroid.within(buf)]
    pop = in_buf["obyvatelstvo_celkem"].sum()
    # Frýdek-Místek region: realisticky 200k–1M obyvatel
    assert 200_000 <= pop <= 1_000_000, f"Populace {pop:,.0f} mimo očekávaný rozsah"


def test_age_structure_sums_to_total():
    gdf = gpd.read_file(
        os.path.join(DATA_DIR, "obce_sldb",
                     "csu_geodb_sde_CISOB_obyvatelstvo_etl_20210326.gpkg")
    )
    col_map = {
        "gis131620000": "total",
        "gis131620011": "age_0_14",
        "gis131620012": "age_15_64",
        "gis131620013": "age_65plus",
    }
    gdf = gdf.rename(columns=col_map)
    valid = gdf[gdf["total"].notna()].head(100)
    age_sum = valid["age_0_14"] + valid["age_15_64"] + valid["age_65plus"]
    diff = (age_sum - valid["total"]).abs()
    # Tolerance 1 osoba na obec (zaokrouhlení)
    assert (diff <= 1.5).all(), "Součet věkových skupin neodpovídá celkovému počtu"


# ---------------------------------------------------------------------------
# Spots
# ---------------------------------------------------------------------------

def test_spots_in_buffer():
    spots = gpd.read_file(os.path.join(DATA_DIR, "marketing-spots-fm.gpkg"))
    fm = gpd.GeoDataFrame([{"geometry": Point(FM_LON, FM_LAT)}], crs=CRS_WGS)
    buf = fm.to_crs(CRS_METRIC).buffer(20_000).iloc[0]
    spots_m = spots.to_crs(CRS_METRIC)
    in_buf = spots_m[spots_m.geometry.within(buf)]
    assert len(in_buf) > 500, f"Příliš málo spotů v bufferu: {len(in_buf)}"


def test_spots_have_expected_categories():
    spots = gpd.read_file(os.path.join(DATA_DIR, "marketing-spots-fm.gpkg"))
    amenity_vals = set(spots["amenity"].dropna().unique())
    for expected in ("restaurant", "pub", "fast_food", "cafe"):
        assert expected in amenity_vals, f"Chybí kategorie amenity='{expected}'"


# ---------------------------------------------------------------------------
# Output files
# ---------------------------------------------------------------------------

def test_isochrone_file_exists():
    path = os.path.join(DATA_DIR, "isochrone_20min.geojson")
    assert os.path.exists(path), "Chybí isochrone_20min.geojson"
    with open(path) as f:
        data = json.load(f)
    assert "features" in data and len(data["features"]) > 0
    feat = data["features"][0]
    assert feat["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_isochrone_area_reasonable():
    import json
    from shapely.geometry import shape
    path = os.path.join(DATA_DIR, "isochrone_20min.geojson")
    with open(path) as f:
        data = json.load(f)
    geom = shape(data["features"][0]["geometry"])
    iso_gdf = gpd.GeoDataFrame([{"geometry": geom}], crs="EPSG:4326").to_crs("EPSG:5514")
    area_km2 = iso_gdf.geometry.area.values[0] / 1e6
    # 20 min drive ~500–1200 km² is realistic for FM area
    assert 300 <= area_km2 <= 1500, f"Plocha izochrony {area_km2:.0f} km² mimo očekávání"


def test_grid_data_loads():
    grid_path = os.path.join(DATA_DIR, "gridy_domacnosti",
                             "grid_domacnosti_sldb2021_20210326.gpkg")
    assert os.path.exists(grid_path), "Chybí grid data"
    gdf = gpd.read_file(grid_path, rows=10)
    assert "g179999001" in gdf.columns
    assert gdf.crs is not None


def test_grid_households_in_buffer():
    grid_path = os.path.join(DATA_DIR, "gridy_domacnosti",
                             "grid_domacnosti_sldb2021_20210326.gpkg")
    gdf = gpd.read_file(grid_path).rename(columns={"g179999001": "hh_celkem"})
    fm = gpd.GeoDataFrame([{"geometry": Point(FM_LON, FM_LAT)}], crs="EPSG:4326")
    buf = fm.to_crs("EPSG:5514").buffer(20_000).iloc[0]
    gdf_m = gdf.to_crs("EPSG:5514")
    in_buf = gdf_m[gdf_m.geometry.centroid.within(buf)]
    hh_total = in_buf["hh_celkem"].sum()
    assert 100_000 <= hh_total <= 500_000, f"Domácností {hh_total:,} mimo očekávaný rozsah"


def test_output_files_exist():
    for fname in (
        "vecerkaplus_mapa.html",
        "obce_v_dosahu.csv",
        "marketing_spots_kategorie.csv",
        "souhrn.csv",
    ):
        path = os.path.join(OUT_DIR, fname)
        assert os.path.exists(path), f"Chybí výstupní soubor: {fname}"


def test_output_csv_obce_structure():
    df = pd.read_csv(os.path.join(OUT_DIR, "obce_v_dosahu.csv"))
    assert len(df) > 0
    for col in ("nazev", "obyvatelstvo_celkem"):
        assert col in df.columns, f"Chybí sloupec '{col}' v obce_v_dosahu.csv"
    assert df["obyvatelstvo_celkem"].sum() > 100_000


def test_output_map_is_html():
    path = os.path.join(OUT_DIR, "vecerkaplus_mapa.html")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read(500)
    assert "<!DOCTYPE html>" in content or "<html" in content.lower()
