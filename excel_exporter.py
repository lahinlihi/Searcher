"""
Excel 내보내기 기능
공고 데이터를 CSV 또는 Excel 파일로 내보냅니다.
"""

import csv
import io
from datetime import datetime


class ExcelExporter:
    """Excel/CSV 내보내기 클래스"""

    def __init__(self):
        self.headers = [
            '상태', '공고명', '발주기관', '공고번호',
            '공고일', '마감일', '개찰일',
            '추정가격', '입찰방식', '중소기업',
            '출처', 'URL'
        ]

    def export_to_csv(self, tenders, filename=None):
        """
        CSV로 내보내기

        Args:
            tenders (list): 공고 리스트
            filename (str): 파일명 (None이면 자동 생성)

        Returns:
            str: CSV 문자열
        """
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'tenders_{timestamp}.csv'

        # CSV 문자열 생성
        output = io.StringIO()
        writer = csv.writer(output)

        # 헤더 작성
        writer.writerow(self.headers)

        # 데이터 작성
        for tender in tenders:
            row = self._tender_to_row(tender)
            writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        return csv_content

    def export_to_excel_html(self, tenders):
        """
        Excel에서 열 수 있는 HTML 테이블로 내보내기

        Args:
            tenders (list): 공고 리스트

        Returns:
            str: HTML 문자열
        """
        html = """
        <html xmlns:o="urn:schemas-microsoft-com:office:office"
              xmlns:x="urn:schemas-microsoft-com:office:excel"
              xmlns="http://www.w3.org/TR/REC-html40">
        <head>
            <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
            <style>
                table { border-collapse: collapse; width: 100%; }
                th { background-color: #2563EB; color: white; padding: 10px; border: 1px solid #ddd; }
                td { padding: 8px; border: 1px solid #ddd; }
                tr:nth-child(even) { background-color: #f9f9f9; }
                .pre { background-color: #DBEAFE; font-weight: bold; }
            </style>
        </head>
        <body>
            <table>
                <thead>
                    <tr>
        """

        # 헤더
        for header in self.headers:
            html += f"<th>{header}</th>"

        html += """
                    </tr>
                </thead>
                <tbody>
        """

        # 데이터
        for tender in tenders:
            row_class = 'pre' if tender.get('status') == '사전규격' else ''
            html += f'<tr class="{row_class}">'

            row = self._tender_to_row(tender)
            for cell in row:
                html += f"<td>{cell}</td>"

            html += "</tr>"

        html += """
                </tbody>
            </table>
        </body>
        </html>
        """

        return html

    def export_by_status(self, tenders):
        """
        상태별로 구분하여 내보내기

        Args:
            tenders (list): 공고 리스트

        Returns:
            dict: {'pre': csv_content, 'normal': csv_content}
        """
        pre_tenders = [t for t in tenders if t.get('status') == '사전규격']
        normal_tenders = [t for t in tenders if t.get('status') != '사전규격']

        return {
            'pre': self.export_to_csv(pre_tenders),
            'normal': self.export_to_csv(normal_tenders),
            'all': self.export_to_csv(tenders)
        }

    def _tender_to_row(self, tender):
        """공고 데이터를 CSV 행으로 변환"""
        # 날짜 포맷
        announced_date = self._format_date(tender.get('announced_date'))
        deadline_date = self._format_date(tender.get('deadline_date'))
        opening_date = self._format_date(tender.get('opening_date'))

        # 가격 포맷
        price = self._format_price(tender.get('estimated_price'))

        # 중소기업 여부
        sme = 'O' if tender.get('is_sme_only') else 'X'

        return [
            tender.get('status', '일반'),
            tender.get('title', ''),
            tender.get('agency', ''),
            tender.get('tender_number', ''),
            announced_date,
            deadline_date,
            opening_date,
            price,
            tender.get('bid_method', ''),
            sme,
            tender.get('source_site', ''),
            tender.get('url', '')
        ]

    def _format_date(self, date_obj):
        """날짜 포맷"""
        if not date_obj:
            return ''

        if isinstance(date_obj, datetime):
            return date_obj.strftime('%Y-%m-%d')
        else:
            return str(date_obj)

    def _format_price(self, price):
        """가격 포맷"""
        if not price:
            return ''

        return f"{price:,}원"


# 전역 인스턴스
excel_exporter = ExcelExporter()
