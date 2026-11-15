"""Public feature copy, checked against the app's routes and screens.

Keep unverified descriptions empty until the owner supplies the details.
Source comments are for future copy reviews; they are not shown to visitors.
"""

FEATURES = [
    # employee.ticket_verification, user driver/spectator checkout, order_service
    {
        "id": "ticketing", "name": "Ticketing & admissions",
        "headline": "Account for every entry.",
        "summary": "Drivers, spectators and vendors all come through your gates. Track Ops connects their tickets, payment status and check-ins so your staff can see who has paid and who has arrived.",
        "details": [
            ("Set up your admissions", "Set driver, spectator and vendor pricing and capacity for each event. Customers purchase the appropriate entry, with online checkout through your configured payment provider."),
            ("Verify at the gate", "Scan a ticket, enter its code or look up the attendee by name. Staff can see the event, ticket type and payment status before admitting someone."),
            ("Keep a record of entry", "Tickets with unconfirmed payments are locked from admission. Already-used tickets and checked-in drivers are flagged, helping your crew catch repeat entry attempts."),
        ],
    },
    # employee.events_index / event_detail, event_detail.html analytics tab
    {
        "id": "events", "name": "Events & reporting",
        "headline": "Give the whole event a home.",
        "summary": "Bring the calendar, registrations and event-day tools into one workspace. Staff can move from event setup to participants, inspections, the schedule and live track activity without hunting through separate records.",
        "details": [
            ("Build the event", "Set the date, operating hours, track layout, ticket prices and capacity. Your events calendar brings event dates and private rental availability together."),
            ("See who is coming", "Review registered drivers and their vehicles, check-in status and class assignments. Keep the roster tied to the event your crew is running."),
            ("Review the numbers", "Office staff can view signup trends and driver class breakdowns in the event’s Analytics tab. Capacity counts show how entries compare with the limits you set."),
        ],
    },
    # employee.inspection_rules / inspections_hub / inspect_registration
    {
        "id": "tech-inspections", "name": "Digital tech inspections",
        "headline": "Get the clipboard out of the way.",
        "summary": "Run tech from a digital checklist built for your track. Each inspection stays with the driver’s event registration and vehicle, giving staff a clear record of what was checked and what still needs attention.",
        "details": [
            ("Use your track’s checklist", "Create inspection conditions and enable the ones your inspectors need. The active checklist is used when staff inspect a registered vehicle."),
            ("Find the driver and work through tech", "Use a check-in code or driver lookup to open the registration. Mark each condition and add inspector notes directly to the inspection record."),
            ("Keep the result with the entry", "An inspection passes when every active checklist item is checked. Staff can reopen the saved record, review notes and update the checklist as issues are resolved."),
        ],
    },
    # waiver_routes, waiver_service, employee.driver_checkin and waiver template tools
    {
        "id": "digital-waivers", "name": "Digital waivers",
        "headline": "Signed before the check-in line.",
        "summary": "Let drivers complete required waivers digitally before arrival. Track Ops keeps signing status connected to the driver and event, so the person at check-in can see whether the required waiver is complete.",
        "details": [
            ("Choose the right waiver", "Manage waiver templates for your track and select the waiver for an event. Events can use the track’s required default when an event-specific template has not been selected."),
            ("Give drivers a signing flow", "Drivers open their waivers and sign through the connected BoldSign service. Their waiver list tracks sent and signed status and refreshes after signing."),
            ("Check the paperwork at check-in", "Driver check-in is blocked while a required waiver is missing or unsigned. Signed records retain their completion time, with a PDF link when the signing service supplies one."),
        ],
    },
    # employee.event_detail slots, event_class_slot_*, event_lineup_lanes
    {
        "id": "scheduling", "name": "Schedules & lineup lanes",
        "headline": "Give each class its time on track.",
        "summary": "Turn your event hours into a schedule your crew and drivers can refer to. Track Ops puts class times and lineup lane assignments alongside the event’s participant records.",
        "details": [
            ("Plan class sessions", "Office staff set start and end times for driver classes within the event window. Track staff can read the schedule from the same event workspace."),
            ("Organize the lineup", "Configure lineup lanes for the event and assign driver classes to them, giving your team a reference for staging."),
            ("Keep drivers informed", "Registered drivers can view the event schedule from their account. When staff update the schedule, it stays attached to the event."),
        ],
    },
    # scanner_api._driver_eligibility / _record_run_transition, employee.live_track
    {
        "id": "vehicle-tracking", "name": "Vehicle tracking",
        "headline": "Know who’s on track.",
        "summary": "RFID vehicle tags and configured entrance and exit scanners update on-track status. Your team can see vehicles entering and leaving through the Live Track view as the event runs.",
        "details": [
            ("Connect the vehicle", "Link a tag to a car and configure scanners for track entrance and track exit. Scanner observations connect vehicle activity to the track and event."),
            ("See entry readiness", "The scanner checks event registration, a passed event inspection and, for public events, confirmed driver ticket payment. Ineligible observations include a reason for staff to review."),
            ("Follow track activity", "Entrance and exit observations update on-track status and record run participation. Status changes as tagged vehicles pass the configured scanners."),
        ],
    },
    # user.attendee_run_vote, employee.event_run_voting
    {
        "id": "spectator-interaction", "name": "Spectator interaction",
        "headline": "Let the crowd be part of it.",
        "summary": "Give ticketed attendees a way to follow the event and react to runs from their phones. The live event experience brings the drivers and vehicles in a run closer to the people watching.",
        "details": [
            ("Open the live event", "Eligible ticket holders can access the event’s live track view and see current activity and recorded runs."),
            ("Turn on audience voting", "Office staff control whether run voting is enabled for each event. Attendees can give a run a thumbs up or thumbs down."),
            ("Keep it to one vote", "Each attendee can rate a run once. Recorded ratings appear in the event’s live view, giving spectators an easy way to participate."),
        ],
    },
    # employee.run_history, camera_api, templates/employee/run_history.html
    {
        "id": "run-history", "name": "Run history & video",
        "headline": "Keep the story of every run.",
        "summary": "Recorded runs stay with the event after the vehicles leave the track. Staff can review who participated, when they entered and exited, and any available video attached to the run.",
        "details": [
            ("Build the run record", "Scanner-driven activity creates run and participant records, including the driver, vehicle and entry and exit times."),
            ("Review past activity", "The event’s Run History screen lists saved runs and their status. Driver and vehicle details sit alongside each participant’s times."),
            ("Watch available footage", "With the camera integration configured, ready run videos can be played from the run record. Video status is shown while footage is being processed."),
        ],
    },
    # employee.driver_profile / add_driver_note / update_driver_class; user.car_new
    {
        "id": "driver-profiles", "name": "Driver profiles & vehicles",
        "headline": "Know the drivers who come back.",
        "summary": "Keep useful context between events. Drivers maintain their vehicle details, while your staff can review a driver’s history at your track, class assignments and internal notes.",
        "details": [
            ("Maintain a garage", "Drivers add and edit their cars, including vehicle details and a photo, then select a vehicle when registering for an event."),
            ("Review their track history", "Staff profiles bring together event registrations, the vehicles used and inspection records for that driver at your track."),
            ("Keep staff context", "Set track-specific driver classes, review class changes and add internal notes with the author recorded. Your next shift has the same context to work from."),
        ],
    },
    # vendor.dashboard / profile; employee.vendors / vendor_directory
    {
        "id": "vendors", "name": "Vendor management",
        "headline": "Know which businesses are on site.",
        "summary": "Give vendors their own accounts and keep their admission connected to the event. Your crew can see the businesses attending, their passes and whether they have checked in.",
        "details": [
            ("Keep a reusable business profile", "Vendors maintain a business name, logo, description and website, alongside their contact information. Their public business page can be used across events."),
            ("Keep passes in one place", "The vendor dashboard shows purchased passes, upcoming passes and ticket history across Track Ops venues."),
            ("See arrivals", "Staff can filter vendors by event and review total passes, on-site counts and businesses represented. Office staff can also view representative and contact details."),
        ],
    },
    # employee.private_rentals, user.private_rental_calendar, rental_service
    {
        "id": "private-rentals", "name": "Private track rentals",
        "headline": "Put open track time to work.",
        "summary": "Publish bookable private rental times alongside your event calendar. Drivers can browse available slots, and office staff can see which times are available, held at checkout or booked.",
        "details": [
            ("Define the availability", "Create rental slots with a date, start and end time, price and driver limit. Availability is checked against events and other rental slots."),
            ("Let drivers book", "Drivers browse the track’s rental calendar and choose an available slot. A checkout hold separates a booking in progress from a confirmed reservation."),
            ("Keep the calendar current", "Staff can review upcoming availability, booking status and the confirmed renter. Unbooked slots can be removed when plans change."),
        ],
    },
    # user.community / community_post_create / attendee_run_share / subscribe_track
    {
        "id": "community", "name": "Driver community",
        "headline": "Keep the connection after the event.",
        "summary": "Give drivers a place to connect around the cars and events they share. Track Ops includes a community feed, driver connections and track following inside the same account they use for event day.",
        "details": [
            ("Share garage updates", "Drivers can post updates and photos, comment on posts and connect with other drivers."),
            ("Share a run", "Attendees can share completed runs to the community, linking the event, participants and available run video to the post."),
            ("Follow tracks", "Drivers can browse the track directory and follow venues from their account, keeping their track interests alongside their event activity."),
        ],
    },
    # employee.has_office_access / staff_accounts / update_employee_role
    {
        "id": "staff", "name": "Staff accounts & access",
        "headline": "Give your crew the tools for their job.",
        "summary": "Track staff and office staff use individual accounts with different access. The people working the event can reach operational tools, while office functions sit behind the appropriate role.",
        "details": [
            ("Create staff accounts", "Manage named staff accounts for your track and assign a track staff or office staff role."),
            ("Separate daily responsibilities", "Track staff use event tools such as ticket verification, inspections and live activity. Office staff also manage back-office tasks such as event settings and analytics."),
            ("Maintain access", "Authorized staff can update roles and reset employee passwords from the staff account screen."),
        ],
    },
    # Owner review: no verified bulk customer announcement workflow found.
    # Intentionally blank at the owner's request; do not invent feature behavior.
    {
        "id": "customer-communications", "name": "Customer communications",
        "headline": "", "summary": "", "details": [],
    },
]
