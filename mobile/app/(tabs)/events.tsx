import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate, money } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

export default function EventsScreen() {
  const { account, api } = useAuth(); const [events, setEvents] = useState<TrackEvent[] | null>(null);
  useEffect(() => { if (!account) return; api<{ events: TrackEvent[] }>(account.type === 'employee' ? '/staff/events' : '/driver/events').then(body => setEvents(body.events)).catch(() => setEvents([])); }, [account, api]);
  if (!events) return <Loading />;
  return <Screen><Hero eyebrow="Calendar" title={account?.type === 'employee' ? 'Track schedule' : 'Find your next track day'} subtitle={account?.type === 'employee' ? 'Choose an event to check in drivers, inspect cars, manage the schedule, or run the track.' : 'Clear availability, pricing, and event details.'} />
    {account?.type === 'employee' && account.role === 'office_staff' ? <><SectionTitle title="Planning" /><Card style={styles.planning}><Pressable onPress={() => router.push('/event-planning/new')} style={styles.planRow}><View style={styles.planCopy}><Text style={ui.title}>Create an event</Text><Text style={ui.body}>Set the date, prices, capacity, waiver, and track layout.</Text></View><Text style={styles.arrow}>›</Text></Pressable><Pressable onPress={() => router.push('/event-planning/rentals')} style={[styles.planRow, styles.planDivider]}><View style={styles.planCopy}><Text style={ui.title}>Private rental availability</Text><Text style={ui.body}>Publish rental slots and manage bookings.</Text></View><Text style={styles.arrow}>›</Text></Pressable></Card></> : null}
    <SectionTitle title={account?.type === 'employee' ? 'Events' : 'Upcoming events'} />
    {events.length ? events.map(event => <Pressable key={event.id} onPress={() => router.push(`/event/${event.id}`)}><Card><View style={ui.between}><View style={styles.date}><Text style={styles.dateDay}>{new Date(`${event.date}T12:00:00`).getDate()}</Text><Text style={styles.dateMonth}>{new Date(`${event.date}T12:00:00`).toLocaleString('en-US', { month: 'short' }).toUpperCase()}</Text></View><View style={styles.info}><Text style={ui.title}>{event.name}</Text><Text style={ui.body}>{eventDate(event.date)}</Text><Text style={ui.body}>{event.track.name} · {event.track.location}</Text></View><Text style={styles.arrow}>›</Text></View>{account?.type === 'user' ? <View style={styles.footer}><Text style={styles.price}>Driver {money(event.prices.driver)}</Text><Text style={[ui.pill, { overflow: 'hidden' }]}>{event.has_driver_ticket ? 'Booked' : event.availability?.driver?.sold_out ? 'Sold out' : 'Available'}</Text></View> : null}</Card></Pressable>) : <Empty title="No upcoming events" detail="There are no events available right now." />}
  </Screen>;
}
const styles = StyleSheet.create({ planning: { paddingVertical: 2 }, planRow: { minHeight: 72, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 12 }, planCopy: { flex: 1, paddingRight: 12 }, planDivider: { borderTopWidth: 1, borderTopColor: palette.line }, date: { width: 54, height: 58, borderRadius: 13, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' }, dateDay: { color: palette.orange, fontSize: 21, fontWeight: '900' }, dateMonth: { color: '#C2410C', fontSize: 10, fontWeight: '900' }, info: { flex: 1, paddingHorizontal: 12 }, arrow: { color: palette.orange, fontSize: 28 }, footer: { borderTopWidth: 1, borderTopColor: palette.line, marginTop: 14, paddingTop: 12, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, price: { color: palette.ink, fontWeight: '800' } });
