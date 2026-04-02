"""
이메일 알림 기능
새 공고 및 마감 임박 공고에 대한 이메일 알림을 발송합니다.
"""

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


class EmailNotifier:
    """이메일 알림 클래스"""

    # 이메일 서비스별 SMTP 설정
    SMTP_SETTINGS = {
        'gmail': {
            'name': 'Gmail',
            'server': 'smtp.gmail.com',
            'port': 587,
            'requires_app_password': True,
            'help_url': 'https://myaccount.google.com/apppasswords'
        },
        'naver': {
            'name': '네이버',
            'server': 'smtp.naver.com',
            'port': 587,
            'requires_app_password': False,
            'help_url': 'https://mail.naver.com'
        },
        'daum': {
            'name': '다음/카카오',
            'server': 'smtp.daum.net',
            'port': 465,
            'requires_app_password': False,
            'use_ssl': True,
            'help_url': 'https://mail.daum.net'
        },
        'outlook': {
            'name': 'Outlook/Hotmail',
            'server': 'smtp-mail.outlook.com',
            'port': 587,
            'requires_app_password': False,
            'help_url': 'https://outlook.live.com'
        }
    }

    def __init__(self, smtp_server='smtp.gmail.com', smtp_port=587):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.use_ssl = False
        self.enabled = False
        self.sender_email = None
        self.sender_password = None
        self.recipient_email = None
        self.email_service = 'gmail'

    def configure(
            self,
            sender_email,
            sender_password,
            recipient_email,
            email_service='gmail'):
        """
        이메일 설정

        Args:
            sender_email (str): 발신자 이메일
            sender_password (str): 발신자 비밀번호 (앱 비밀번호)
            recipient_email (str): 수신자 이메일
            email_service (str): 이메일 서비스 종류 (gmail, naver, daum, outlook)
        """
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.recipient_email = recipient_email
        self.email_service = email_service

        # 이메일 서비스에 맞는 SMTP 설정 적용
        if email_service in self.SMTP_SETTINGS:
            settings = self.SMTP_SETTINGS[email_service]
            self.smtp_server = settings['server']
            self.smtp_port = settings['port']
            self.use_ssl = settings.get('use_ssl', False)

        self.enabled = True

    def send_new_tenders_notification(self, tenders):
        """
        새 공고 알림 발송

        Args:
            tenders (list): 새 공고 리스트

        Returns:
            bool: 성공 여부
        """
        if not self.enabled or not tenders:
            return False

        try:
            subject = f"[입찰공고] 새로운 공고 {len(tenders)}건"
            body = self._create_new_tenders_email_body(tenders)

            return self._send_email(subject, body)

        except Exception as e:
            print(f"[이메일] 새 공고 알림 발송 실패: {str(e)}")
            return False

    def send_deadline_alert(self, tenders):
        """
        마감 임박 공고 알림 발송

        Args:
            tenders (list): 마감 임박 공고 리스트

        Returns:
            bool: 성공 여부
        """
        if not self.enabled or not tenders:
            return False

        try:
            subject = f"[입찰공고] 마감 임박 공고 {len(tenders)}건"
            body = self._create_deadline_alert_email_body(tenders)

            return self._send_email(subject, body)

        except Exception as e:
            print(f"[이메일] 마감 임박 알림 발송 실패: {str(e)}")
            return False

    def send_test_email(self):
        """
        테스트 이메일 발송

        Returns:
            bool: 성공 여부
        """
        if not self.sender_email or not self.sender_password or not self.recipient_email:
            return False

        try:
            subject = "[입찰공고 시스템] 테스트 이메일"
            body = self._create_test_email_body()

            # 임시로 enabled를 True로 설정
            original_enabled = self.enabled
            self.enabled = True

            result = self._send_email(subject, body)

            # 원래 상태로 복원
            self.enabled = original_enabled

            return result

        except Exception as e:
            print(f"[이메일] 테스트 이메일 발송 실패: {str(e)}")
            return False

    def _send_email(self, subject, body):
        """
        이메일 발송

        Args:
            subject (str): 제목
            body (str): 본문 (HTML)

        Returns:
            bool: 성공 여부
        """
        try:
            message = MIMEMultipart('alternative')
            message['Subject'] = subject
            message['From'] = self.sender_email
            message['To'] = self.recipient_email

            # HTML 본문 추가
            html_part = MIMEText(body, 'html', 'utf-8')
            message.attach(html_part)

            # SMTP 연결 및 발송
            if self.use_ssl:
                # SSL 사용 (다음/카카오)
                import smtplib
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port) as server:
                    server.login(self.sender_email, self.sender_password)
                    server.send_message(message)
            else:
                # STARTTLS 사용 (Gmail, 네이버, Outlook)
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.sender_email, self.sender_password)
                    server.send_message(message)

            print(f"[이메일] 알림 발송 완료: {self.recipient_email}")
            return True

        except Exception as e:
            print(f"[이메일] 발송 실패: {str(e)}")
            return False

    def _create_new_tenders_email_body(self, tenders):
        """새 공고 이메일 본문 생성"""
        html = """
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .header {{ background-color: #2563EB; color: white; padding: 20px; }}
                .content {{ padding: 20px; }}
                .tender {{ border: 1px solid #E5E7EB; margin: 10px 0; padding: 15px; border-radius: 5px; }}
                .tender-title {{ font-weight: bold; font-size: 16px; color: #111827; }}
                .tender-info {{ color: #6B7280; font-size: 14px; margin-top: 5px; }}
                .badge {{ display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 12px; }}
                .badge-pre {{ background-color: #DBEAFE; color: #1E40AF; }}
                .footer {{ padding: 20px; text-align: center; color: #6B7280; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>새로운 입찰공고 {len(tenders)}건</h1>
                <p>{datetime.now().strftime('%Y년 %m월 %d일')}</p>
            </div>
            <div class="content">
        """

        for tender in tenders[:10]:  # 최대 10건만
            # status_badge는 현재 사용되지 않음
            # status_badge = ''
            # if tender.get('status') == '사전규격':
            #     status_badge = '<span class="badge badge-pre">사전규격</span>'

            self._format_price(tender.get('estimated_price'))
            deadline = tender.get('deadline_date')
            if isinstance(deadline, datetime):
                deadline.strftime('%Y-%m-%d')
            else:
                str(deadline) if deadline else '미정'

            html += """
                <div class="tender">
                    <div class="tender-title">
                        {status_badge} {tender.get('title', '제목 없음')}
                    </div>
                    <div class="tender-info">
                        발주: {tender.get('agency', '미정')} |
                        금액: {price} |
                        마감: {deadline_str}
                    </div>
                </div>
            """

        if len(tenders) > 10:
            html += f"<p>외 {len(tenders) - 10}건...</p>"

        html += """
            </div>
            <div class="footer">
                <p>입찰공고 통합 검색 시스템</p>
                <p>이 메일은 자동으로 발송되었습니다.</p>
            </div>
        </body>
        </html>
        """

        return html

    def _create_deadline_alert_email_body(self, tenders):
        """마감 임박 이메일 본문 생성"""
        html = """
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .header {{ background-color: #EF4444; color: white; padding: 20px; }}
                .content {{ padding: 20px; }}
                .tender {{ border: 1px solid #FEE2E2; background-color: #FEF2F2;
                           margin: 10px 0; padding: 15px; border-radius: 5px; }}
                .tender-title {{ font-weight: bold; font-size: 16px; color: #991B1B; }}
                .tender-info {{ color: #DC2626; font-size: 14px; margin-top: 5px; }}
                .urgent {{ color: #EF4444; font-weight: bold; }}
                .footer {{ padding: 20px; text-align: center; color: #6B7280; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>⚠️ 마감 임박 공고 {len(tenders)}건</h1>
                <p>{datetime.now().strftime('%Y년 %m월 %d일')}</p>
            </div>
            <div class="content">
                <p class="urgent">다음 공고들의 마감일이 곧 다가옵니다!</p>
        """

        for tender in tenders[:10]:
            self._format_price(tender.get('estimated_price'))
            deadline = tender.get('deadline_date')

            if isinstance(deadline, datetime):
                deadline.strftime('%Y-%m-%d')
                (deadline - datetime.now()).days
            else:
                pass

            html += """
                <div class="tender">
                    <div class="tender-title">
                        {tender.get('title', '제목 없음')}
                    </div>
                    <div class="tender-info">
                        발주: {tender.get('agency', '미정')} |
                        금액: {price} |
                        마감: {deadline_str} <span class="urgent">(D-{days_left})</span>
                    </div>
                </div>
            """

        if len(tenders) > 10:
            html += f"<p>외 {len(tenders) - 10}건...</p>"

        html += """
            </div>
            <div class="footer">
                <p>입찰공고 통합 검색 시스템</p>
                <p>이 메일은 자동으로 발송되었습니다.</p>
            </div>
        </body>
        </html>
        """

        return html

    def _create_test_email_body(self):
        """테스트 이메일 본문 생성"""
        html = """
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .header {{ background-color: #2563EB; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 30px; text-align: center; }}
                .success-icon {{ font-size: 48px; color: #10B981; }}
                .info-box {{ background-color: #F3F4F6; border-radius: 5px;
                            padding: 20px; margin: 20px 0; }}
                .footer {{ padding: 20px; text-align: center; color: #6B7280;
                          font-size: 12px; border-top: 1px solid #E5E7EB; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>입찰공고 통합 검색 시스템</h1>
            </div>
            <div class="content">
                <div class="success-icon">✓</div>
                <h2>이메일 설정 테스트</h2>
                <p>이메일 알림 설정이 정상적으로 작동합니다!</p>

                <div class="info-box">
                    <p><strong>설정 완료</strong></p>
                    <p>발신 이메일: {self.sender_email}</p>
                    <p>수신 이메일: {self.recipient_email}</p>
                    <p>테스트 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}</p>
                </div>

                <p>앞으로 다음 알림을 받으실 수 있습니다:</p>
                <ul style="text-align: left; display: inline-block;">
                    <li>새 공고 등록 알림</li>
                    <li>마감 임박 공고 알림 (D-3)</li>
                    <li>관심 키워드 포함 공고 알림</li>
                </ul>
            </div>
            <div class="footer">
                <p>본 이메일은 입찰공고 통합 검색 시스템에서 자동으로 발송되었습니다.</p>
                <p>이메일 알림을 중단하려면 설정 페이지에서 알림을 비활성화하세요.</p>
            </div>
        </body>
        </html>
        """
        return html

    def _format_price(self, price):
        """가격 포맷팅"""
        if not price:
            return '미정'

        if price >= 100000000:
            return f"{price / 100000000:.1f}억원"
        elif price >= 10000000:
            return f"{price / 10000000:.1f}천만원"
        elif price >= 10000:
            return f"{price / 10000:.0f}만원"
        else:
            return f"{price:,}원"


# 전역 인스턴스
email_notifier = EmailNotifier()
