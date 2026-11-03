# Your account and API tokens

The shop's own pages talk to the same **API** that other programs can use.
The **Account** page shows what that costs and which keys you have.

## API tokens

Every request to the shop's `/api` costs **tokens**:

| request | tokens |
| --- | --- |
| looking at bikes, prices, availability, a quote | 1 |
| booking a rental, reserving a bike | 5 |
| cancelling | free |

A new account starts with **100 tokens**. When they run out, the shop says
so and links to the Account page, where you can **buy more**. This is part of
the demo: no money changes hands.

Tokens pay for using the API, not for bikes: bike prices are paid in the shop.

## Limits

To keep the shop fast for everybody, an account can make at most **60
requests a minute**, 1,000 an hour and 5,000 a day. The Account page shows
how many you have left.

## API keys

Signing in creates an API key for the browser tab (see
[getting started](getting-started.md)). Your own programs, for example a
script that checks availability, get a key from `POST /auth/generate-key`
with your username and password. The Account page lists all your keys;
**Revoke** cancels one at once.

Keep keys secret: anyone with your key can book in your name. The API
documentation is at `/docs`.
