
from openpyxl import Workbook
from fastapi.responses import StreamingResponse
import io


def generate_excel_report(data):

    wb = Workbook()

    ws = wb.active
    ws.title = "Stock Report"

    headers = [
        "Institution",
        "Asset",
        "Category",
        "Total",
        "Available",
        "Status"
    ]

    ws.append(headers)

    for row in data:

        ws.append([
            row["institution"],
            row["asset"],
            row["category"],
            row["total"],
            row["available"],
            row["status"]
        ])

    buffer = io.BytesIO()

    wb.save(buffer)

    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition":
            "attachment; filename=stock_report.xlsx"
        }
    )
