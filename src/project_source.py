"""Project only the declared simulation fields,with explicit native-value states."""

import argparse, csv, gzip, hashlib, io, json, math, platform
from pathlib import Path
import pyarrow, pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "bldg_id",
    "upgrade",
    "completed_status",
    "applicability",
    "in.comstock_building_type",
    "in.sqft",
    "in.weekday_operating_hours",
    "in.weekend_operating_hours",
    "out.site_energy.total.energy_consumption",
    "out.electricity.total.energy_consumption",
]
UNITS = {
    "in.sqft": "ft2",
    "in.weekday_operating_hours": "hr",
    "in.weekend_operating_hours": "hr",
    "out.site_energy.total.energy_consumption": "kwh",
    "out.electricity.total.energy_consumption": "kwh",
}


def token(value):
    if value is None:
        return "null", ""
    if isinstance(value, bool):
        return "bool", "true" if value else "false"
    if isinstance(value, int):
        return "int", str(value)
    if isinstance(value, float):
        return "float", str(value)
    if isinstance(value, str):
        return "text", value
    raise TypeError(type(value).__name__)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("private_dir", type=Path)
    p.add_argument("dictionary_dir", type=Path)
    a = p.parse_args()
    out = ROOT / "data/records.csv.gz"
    manifest = ROOT / "data/source_manifest.json"
    assert not out.exists() and not manifest.exists()
    receipts = json.loads((a.private_dir / "requests.json").read_text(encoding="utf-8"))
    assert len(receipts) == 10 and all(r["status"] == 200 for r in receipts)
    dictionaries = {}
    units = {}
    csv.field_size_limit(4 * 1024 * 1024)
    for weather in ["amy2012", "amy2018"]:
        path = a.dictionary_dir / (weather + "-data_dictionary.tsv")
        with path.open(encoding="utf-8", newline="") as f:
            dictionary = {r["field_name"]: r for r in csv.DictReader(f, delimiter="\t")}
        for field, unit in UNITS.items():
            assert dictionary[field]["units"] == unit, (
                "Dictionary units",
                weather,
                field,
            )
        dictionaries[weather] = dict(
            url="https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2025/comstock_"
            + weather
            + "_release_2/data_dictionary.tsv",
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        units[weather] = [
            {
                k: dictionary[field][k]
                for k in ["field_name", "data_type", "units", "field_description"]
            }
            for field in FIELDS
        ]
    stream = io.StringIO(newline="")
    headers = [
        "source_file",
        "source_row",
        "weather",
        *[v for field in FIELDS for v in [field, field + "__type"]],
    ]
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    counts = {}
    schemas = {}
    for receipt in receipts:
        path = a.private_dir / receipt["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["sha256"]
        source = pq.ParquetFile(path)
        mapping = {}
        for field in FIELDS:
            matches = [
                n for n in source.schema_arrow.names if n.split("..")[0] == field
            ]
            assert len(matches) == 1, (
                "Unique source field",
                receipt["file"],
                field,
                matches,
            )
            name = matches[0]
            if field in UNITS:
                assert name == field + ".." + UNITS[field], ("Header unit", name)
            else:
                assert name == field
            mapping[field] = name
        schemas[receipt["file"]] = dict(
            fields=mapping,
            stored_types={
                field: str(source.schema_arrow.field(name).type)
                for field, name in mapping.items()
            },
            rows=source.metadata.num_rows,
        )
        table = source.read(columns=list(mapping.values()))
        count = 0
        for count, row in enumerate(table.to_pylist(), 1):
            record = dict(
                source_file=receipt["file"],
                source_row=count,
                weather=receipt["weather"],
            )
            for field, name in mapping.items():
                kind, value = token(row[name])
                record[field] = value
                record[field + "__type"] = kind
            assert int(record["upgrade"]) == receipt["upgrade"]
            writer.writerow(record)
        counts[receipt["file"]] = count
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=buffer, mode="wb", mtime=0) as compressed:
        compressed.write(stream.getvalue().encode("utf-8"))
    out.write_bytes(buffer.getvalue())
    (ROOT / "data/dictionary_fields.json").write_bytes(
        (json.dumps(units, indent=2) + "\n").encode()
    )
    value = dict(
        source="ComStock2025Release2,AMY2012/AMY2018,ChittendenCountyVT",
        source_url="https://data.openei.org/submissions/4520",
        attribution="Data includes information from ComStock developed by NLR with DOE funding;Parker etal.2023,ComStockReferenceDocumentation,NREL/TP-5500-83819",
        license="CC BY4.0 with source research/as-is disclaimer",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        changes="Minimal selected fields and explicit native-value states;all source rows retained;analysis deduplication and scenario decisions separately labeled",
        endorsement=False,
        files={
            n: hashlib.sha256((ROOT / "data" / n).read_bytes()).hexdigest()
            for n in ["records.csv.gz", "dictionary_fields.json"]
        },
        fields=FIELDS,
        units=UNITS,
        schemas=schemas,
        rows_by_source=counts,
        source_rows=sum(counts.values()),
        requests=receipts,
        dictionaries=dictionaries,
        runtime=dict(python=platform.python_version(), pyarrow=pyarrow.__version__),
        limits="Published simulations,not physical building records or measured savings;reallocated model copies not independent;source PDFs/dictionaries/raw files private;no national weights or totals",
    )
    manifest.write_bytes((json.dumps(value, indent=2) + "\n").encode())
    print(
        json.dumps(
            dict(
                status="PROJECTED_NOT_INDEPENDENTLY_VERIFIED",
                source_rows=sum(counts.values()),
                compressed_bytes=out.stat().st_size,
                columns=len(headers),
            )
        )
    )


if __name__ == "__main__":
    main()
