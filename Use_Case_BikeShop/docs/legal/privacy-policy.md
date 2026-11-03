# Privacy Policy — BikeShop

> **Draft, pending review.** This text was prepared from the operator's legal
> templates and has not yet been reviewed by a data-protection lawyer or by
> BFH's data-protection office. It may change before it is final.

**Version:** draft of 3 November 2026 · **Operated by:** BFH | W | AIRS lab,
Bern University of Applied Sciences (BFH) · **Contact:** julius.kooistra@bfh.ch

This notice explains which personal data the **BikeShop** demo processes and
why.

## 1. What BikeShop is

BikeShop is a **teaching demo** of the BFH Business School: a worked example of a
web application for a **fictional bike shop**. Nothing is really rented or
sold, and **no payments** are made: rental prices and sale prices are only
recorded, and the "API tokens" you can buy are part of the demo and cost
nothing.

## 2. Who is responsible

The demo is operated by the **BFH | W | AIRS lab** of the Bern University of
Applied Sciences for teaching. Processing follows the data-protection law that
applies to BFH as a public institution of the Canton of Bern.

Students may deploy **their own copy** of BikeShop (for example on Azure). Whoever
runs a copy is responsible for the data in it; this notice covers the demo run
by the AIRS lab.

## 3. What we process

| Category | Examples | Source |
| --- | --- | --- |
| Account data | Username, email address, password (stored only as a one-way hash), role (customer or staff) | You, at registration |
| Rentals and orders | Which bike, the period, the quoted and final price, status changes, reservations and when they expire | You and shop staff, in the app |
| API keys and usage | Key name, when it was created, last used and when it expires (the key itself only as a hash); per request: the endpoint, time and token cost; your token balance and purchases | Recorded by the app |
| Background jobs | Emails waiting to be sent: recipient, subject, status, errors | Recorded by the app |
| Anonymous analytics | Per day: how often the catalogue and bikes were viewed, quotes, bookings, reservations; the bike concerned | Recorded by the app, **without** user id, IP address, time of day or cookies |
| Logs | Time, requested path, status and duration of each request; errors. Email logs record the recipient's **domain** and the subject, never the full address or the text | Recorded by the server |

The app sets **no cookies**. Your sign-in key is kept in your browser tab
(session storage) and is gone when you close the tab. There is no tracking or
advertising, and no data from other sites is loaded.

## 4. Why we process it

- To run the demo: accounts, sign-in, rentals and reservations, and the
  confirmation emails about them.
- To meter and limit use of the API (tokens, rate limits), as part of what
  the demo teaches.
- To see, in aggregate and anonymously, how the shop is used (analytics).
- To operate the service securely and find errors (logs).

We do not sell personal data or use it for any other purpose.

## 5. Who processes it for us

| Provider | What for | Where |
| --- | --- | --- |
| The server hosting the demo | Runs the app and its database | A virtual machine in **Switzerland** |
| Microsoft Azure (student copies only) | Runs a student's copy and stores its database backup | Azure region **Switzerland North** |
| Mailgun (Sinch) | Delivers booking and reservation emails | **EU** region (`api.eu.mailgun.net`) |

Emails to addresses ending in `.test` are never sent.

**AI assistant.** BikeShop may later get an AI assistant that uses **BFH's
own inference service (MLMP)**, which runs on BFH infrastructure. Today the
app only checks that this service can be reached; **no personal data is sent
to it**. Should that change, this notice will be updated first.

## 6. Retention

- **Account data, rentals, orders, API keys and usage**: for as long as the demo
  runs, or until you ask us to delete your account. The demo database may be
  reset at any time, for example at the start of a semester.
- **Sign-in keys** from the web page expire after one day.
- **Anonymous analytics**: 365 days, then deleted automatically.
- **Logs**: for a limited period, for operation and security.

## 7. Your rights

You may ask what data about you is processed, and have it corrected or
deleted. Write to julius.kooistra@bfh.ch.

## 8. Security

The demo is served only over HTTPS. Passwords and API keys are stored only as
one-way hashes. Shop staff functions are available only to staff accounts. The
pages load nothing from other sites.

## 9. Changes

We may update this notice; the current version is posted here with its date.

See also the [Terms of Use](terms-of-service.md).
