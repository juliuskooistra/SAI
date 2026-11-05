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

## Workshop

Every returned bike goes through the diagnostic machine. Bikes still waiting are
listed at the top: press **Run scan**. If the scan finds something, the bike gets a
case.

1. Press **Analyse with the agent**. It reads the scan and prepares your options.
2. Choose an option. The agent answers: it may agree, or argue for something better.
   Discuss it until you are ready.
3. The agent writes the plan. Ask questions, or ask for changes, then approve it.
4. Contact the affected customers from the case: email, call, move or cancel.
5. Record the repair, run a rescan, and put the bike back in service.

A bike that isn't safe can't go back into service until a rescan passes, whatever
anyone decides. Put it **in maintenance** straight away: that doesn't need the agent.

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

The rental price list: an hourly rate, a daily rate and a deposit cap for each
category. The deposit is twice the rental price, but never more than the cap. A change applies to new quotes at once; existing bookings keep the
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
