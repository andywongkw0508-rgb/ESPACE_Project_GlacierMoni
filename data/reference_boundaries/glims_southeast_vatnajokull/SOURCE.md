# GLIMS Southeast Vatnajokull Reference Boundaries

## Source

- Dataset: GLIMS Glacier Database, Version 1 (NSIDC-0272)
- Provider: GLIMS Consortium and NASA NSIDC DAAC
- Layer: `GLIMS:GLIMS_Glacier_Outlines`
- Service: GLIMS Web Feature Service 2.0.0
- Downloaded: 2026-07-12
- Format: GeoJSON
- CRS: EPSG:4326 (WGS 84 longitude/latitude)
- Project AOI query: west -17.15, south 63.90, east -14.75, north 64.95
- Request URL: `https://www.glims.org/geoserver/GLIMS/ows?service=WFS&version=2.0.0&request=GetFeature&typeNames=GLIMS%3AGLIMS_Glacier_Outlines&bbox=-17.15%2C63.90%2C-14.75%2C64.95%2CEPSG%3A4326&srsName=EPSG%3A4326&outputFormat=application%2Fjson`

## Downloaded File

- File: `glims_glacier_outlines_project_aoi_epsg4326.geojson`
- Size: 2,619,423 bytes
- SHA-256: `DB4E52247CA9D43C05E11CBBA6F0A74E258AC07628844E5E417ACA562721E28D`
- Features: 182 polygons
- Boundary type: all records have `line_type=glac_bound`
- Unique analysis IDs: 182
- Unique glacier IDs: 143
- Source dates: 1999-01-01, 2000-09-09, and 2003-08-26
- Source-date range: 1999-01-01 through 2003-08-26

The WFS bounding box selects intersecting features but does not clip their
geometry. The downloaded layer therefore extends west of the project AOI to
longitude -18.17782. Keep this file unchanged as the raw reference source.

## Validation Notes

These GLIMS records predate the project's 2017-2026 Sentinel-2 scenes. Use them
as a historical spatial reference and for gross boundary-quality checks, not as
same-date ground truth for retreat-rate or per-pixel accuracy claims.

GDAL reports one invalid polygon with nested holes: analysis ID 1091198,
glacier ID G342858E64298N, `Skeidararjoekull`, source date 1999-01-01. The raw
download has not been repaired. Any geometry repair, temporal selection, AOI
clipping, or reprojection should be written to a separate validation artifact.

## Documentation And Citation

- Dataset page: https://nsidc.org/data/nsidc-0272
- GLIMS field descriptions: https://www.glims.org/MapsAndDocs/downloaded_field_desc.html
- GLIMS citation guidance: https://www.glims.org/About/citations.html
- Dataset DOI: https://doi.org/10.7265/N5V98602

Suggested dataset citation:

GLIMS Consortium. 2005. GLIMS Glacier Database, Version 1. Boulder, Colorado
USA. NASA National Snow and Ice Data Center Distributed Active Archive Center.
https://doi.org/10.7265/N5V98602. Accessed 2026-07-12. Subset: GLIMS glacier
outlines intersecting the project AOI listed above.
