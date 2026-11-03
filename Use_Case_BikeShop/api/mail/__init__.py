"""
Sending email (SPEC §5.9).

Copied from kooistra-mailer 0.2.0 (`kooistra_mailer/mailer.py`): the Mailgun
and logging backends and `make_mailer`. Changes to the copy:

- synchronous (httpx.Client instead of AsyncClient): the worker runs one job
  at a time in a plain loop, so there is no event loop to share;
- no SMTP backend and no metrics wrapper: the job's row in `job_queue`
  (kind, status, result) is the record of every send (SPEC §10.3);
- the logging backend logs the recipient's domain and the subject only,
  never the full address or the body (SPEC §5.9).

Without MAILGUN_API_KEY, `make_mailer()` returns the logging backend, so a
laptop "sends" email into the log and nothing leaves the machine.
"""
import logging
from typing import Optional, Protocol

import httpx

from .. import config

log = logging.getLogger("bikeshop.mail")


def domain_of(address: str) -> str:
    """'carla@example.ch' -> 'example.ch' (what the logs may show)."""
    return address.rsplit("@", 1)[-1].strip(" >").lower()


class Mailer(Protocol):
    name: str

    def send(self, *, to: str, subject: str, text: str, html: Optional[str] = None) -> None: ...


class LoggingMailer:
    """Logs the email instead of sending it. For local development."""
    name = "logging"

    def __init__(self, default_from: str):
        self.default_from = default_from

    def send(self, *, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
        log.info("EMAIL (logging mailer, not sent) to @%s: %s", domain_of(to), subject,
                 extra={"to_domain": domain_of(to), "subject": subject, "backend": self.name})


class MailgunMailer:
    """Mailgun's HTTP API. For mail.kooistra.ch use the EU base URL: the US one answers 401."""
    name = "mailgun"

    def __init__(self, api_key: str, domain: str, *, default_from: str,
                 base_url: str = "https://api.eu.mailgun.net/v3", timeout: float = 15.0,
                 client: Optional[httpx.Client] = None):
        self.api_key, self.domain, self.default_from = api_key, domain, default_from
        self.base_url, self.timeout, self._client = base_url.rstrip("/"), timeout, client

    def send(self, *, to: str, subject: str, text: str, html: Optional[str] = None) -> None:
        data = {"from": self.default_from, "to": [to], "subject": subject, "text": text}
        if html:
            data["html"] = html
        url = f"{self.base_url}/{self.domain}/messages"
        client = self._client or httpx.Client()
        try:
            response = client.post(url, data=data, auth=("api", self.api_key), timeout=self.timeout)
            response.raise_for_status()   # an error makes the job retry (SPEC §5.8)
        finally:
            if self._client is None:
                client.close()
        log.info("email sent via Mailgun to @%s: %s", domain_of(to), subject,
                 extra={"to_domain": domain_of(to), "subject": subject, "backend": self.name})


def make_mailer() -> Mailer:
    """Mailgun if a key and domain are set, else the logging mailer. Reads config at call time."""
    if config.MAILGUN_API_KEY and config.MAILGUN_DOMAIN:
        return MailgunMailer(config.MAILGUN_API_KEY, config.MAILGUN_DOMAIN,
                             default_from=config.MAIL_FROM, base_url=config.MAILGUN_BASE_URL)
    return LoggingMailer(config.MAIL_FROM)
