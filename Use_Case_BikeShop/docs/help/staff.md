# Staff pages

Shop staff see extra pages in the menu, under **Staff**. Customers don't see
them, and the API refuses their requests to staff functions anyway.

## Today's board

What has to happen at the counter on a day (today by default):

- **Pick-ups due**: bookings that start that day. Press **Pick up** when the
  customer collects the bike (only on the booking's start date).
- **Returns due**: bikes that are out and due back that day. Press
  **Return** when the bike comes back; the page shows the **final price**
  (see [how the price is calculated](renting.md#how-the-price-is-calculated)).
- **Overdue**: bikes past their return time. They stay blocked until they
  are returned.
- **At risk**: bookings for a bike you have put into maintenance. Swap the
  bike or call the customer.

## Inventory

Every bike, including sold and retired ones, with a summary of how many bikes
of each kind are available, out, in maintenance or reserved.

- **Add bike**: rental bikes take their price from the price list; bikes for
  sale need a sale price.
- **Edit**: change any field. A rental bike can be switched between
  *available* and *maintenance*. Its bookings stay and show up as at risk.
- **Retire**: takes a bike out of the catalogue. Not possible while it is
  booked, rented out or reserved.

## Prices

The rental price list: an hourly rate, a daily rate and a deposit for each
category. A change applies to new quotes at once; existing bookings keep the
price they were quoted.

## Orders

Reserved bikes waiting to be paid for. Press **Complete** when the customer
has paid and taken the bike (it is then sold), or **Cancel** to put it back on
sale. Reservations that run past their 7 days are released automatically by
the shop's background worker.

## Analytics

How the shop is used, without knowing who used it: per day, how often the
catalogue and bikes were viewed and how many quotes, bookings and
reservations there were; the 10 most-viewed bikes; and how many quotes became
bookings. No names, accounts or IP addresses are recorded.

## Jobs

Work the shop does in the background, such as sending confirmation emails:
when each job ran, how often it was tried, and any error. A job that fails is
tried again a few times before it is marked as failed.
