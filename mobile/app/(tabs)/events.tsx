import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Card, Empty, Hero, Loading, Screen, ui } from '@/components/ui';
import { eventDate, money } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

export default function EventsScreen() {
  const { account, api } = useAuth(); const [events, setEvents] = useState<TrackEvent[] | null>(null);
  useEffect(() => { if (!account) return; api<{ events: TrackEvent[] }>(account.type === 'employee' ? '/staff/events' : '/driver/events').then(body => setEvents(body.events)).catch(() => setEvents([])); }, [account, api]);
  if (!events) return <Loading />;
  return <Screen><Hero eyebrow="Calendar" title={account?.type === 'employee' ? 'Track schedule' : 'Find your next track day'} subtitle={account?.type === 'employee' ? 'Current and upcoming events at your track.' : 'Clear availability, pricing, and event details.'} />
    {events.length ? events.map(event => <Pressable key={event.id} onPress={() => router.push(`/event/${event.id}`)}><Card><View style={ui.between}><View style={styles.date}><Text style={styles.dateDay}>{new Date(`${event.date}T12:00:00`).getDate()}</Text><Text style={styles.dateMonth}>{new Date(`${event.date}T12:00:00`).toLocaleString('en-US', { month: 'short' }).toUpperCase()}</Text></View><View style={styles.info}><Text style={ui.title}>{event.name}</Text><Text style={ui.body}>{eventDate(event.date)}</Text><Text style={ui.body}>{event.track.name} · {event.track.location}</Text></View><Text style={styles.arrow}>›</Text></View>{account?.type === 'user' ? <View style={styles.footer}><Text style={styles.price}>Driver {money(event.prices.driver)}</Text><Text style={[ui.pill, { overflow: 'hidden' }]}>{event.has_driver_ticket ? 'Booked' : event.availability?.driver?.sold_out ? 'Sold out' : 'Available'}</Text></View> : null}</Card></Pressable>) : <Empty title="No upcoming events" detail="There are no events available right now." />}
  </Screen>;
}
const styles = StyleSheet.create({ date: { width: 54, height: 58, borderRadius: 13, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' }, dateDay: { color: palette.orange, fontSize: 21, fontWeight: '900' }, dateMonth: { color: '#C2410C', fontSize: 10, fontWeight: '900' }, info: { flex: 1, paddingHorizontal: 12 }, arrow: { color: palette.orange, fontSize: 28 }, footer: { borderTopWidth: 1, borderTopColor: palette.line, marginTop: 14, paddingTop: 12, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, price: { color: palette.ink, fontWeight: '800' } });
