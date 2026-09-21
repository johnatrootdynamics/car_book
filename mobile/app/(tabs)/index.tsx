import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { Car, TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type DriverHome = { stats: { events_attended: number; upcoming_events: number; tracks_visited: number; vehicles: number }; upcoming_events: TrackEvent[]; garage: Car[] };
type StaffHome = { stats: { upcoming_events: number; upcoming_drivers: number }; events: TrackEvent[] };
type VendorHome = { stats: { tickets: number; upcoming_events: number; profile_percent: number }; upcoming_events: TrackEvent[] };
type AdminHome = { stats: { tracks: number; staff: number; drivers: number; vendors: number } };

export default function HomeScreen() {
  const { account, api } = useAuth(); const [data, setData] = useState<DriverHome | StaffHome | VendorHome | AdminHome | null>(null); const [error, setError] = useState('');
  useEffect(() => { if (!account) return; setData(null); setError(''); const path = account.type === 'user' ? '/driver/dashboard' : account.type === 'employee' ? '/staff/dashboard' : account.type === 'vendor' ? '/vendor/dashboard' : '/admin/dashboard'; api<any>(path).then(setData).catch(e => setError(e.message)); }, [account, api]);
  if (!account || (!data && !error)) return <Loading />;
  if (account.type === 'user' && data && 'stats' in data) { const driver = data as DriverHome; return <Screen>
    <Hero eyebrow="Driver dashboard" title={`Welcome back, ${account.name.split(' ')[0]}`} subtitle="Everything you need for the next track day." />
    <View style={styles.stats}>{[['Days', driver.stats.events_attended], ['Tracks', driver.stats.tracks_visited], ['Cars', driver.stats.vehicles]].map(([label, value]) => <Card key={String(label)} style={styles.stat}><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></Card>)}</View>
    <SectionTitle title="Upcoming events" />
    {driver.upcoming_events.length ? driver.upcoming_events.slice(0, 4).map(event => <EventRow key={event.id} event={event} />) : <Empty title="No events booked" detail="Your upcoming driver events will appear here." />}
    <SectionTitle title="Your garage" />
    {driver.garage.length ? driver.garage.slice(0, 3).map(car => <Card key={car.id}><Text style={ui.title}>{car.label}</Text><Text style={ui.body}>{car.color || 'Color not listed'}</Text></Card>) : <Empty title="Your garage is empty" detail="Add a car in the Garage tab to use it at checkout." />}
  </Screen>; }
  if (account.type === 'employee' && data && 'events' in data) { const staff = data as StaffHome; const stats = staff.stats || { upcoming_events: staff.events.length, upcoming_drivers: 0 }; return <Screen>
    <Hero eyebrow={account.role === 'office_staff' ? 'Office staff' : 'Track staff'} title={account.track_name || 'Track operations'} subtitle="Fast access to the tools you use at the gate." />
    <View style={styles.stats}>{[['Events', stats.upcoming_events], ['Drivers', stats.upcoming_drivers]].map(([label, value]) => <Card key={String(label)} style={styles.stat}><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></Card>)}</View>
    <Pressable style={styles.scanAction} onPress={() => router.push('/(tabs)/scanner')}><Text style={styles.scanIcon}>⌁</Text><View style={{ flex: 1 }}><Text style={styles.scanTitle}>Open continuous scanner</Text><Text style={styles.scanDetail}>Scan and admit one guest after another.</Text></View><Text style={styles.arrow}>›</Text></Pressable>
    <SectionTitle title="Upcoming at your track" />
    {staff.events.length ? staff.events.slice(0, 6).map(event => <EventRow key={event.id} event={event} />) : <Empty title="No upcoming events" detail="New events will appear here." />}
  </Screen>; }
  if (account.type === 'vendor' && data && 'upcoming_events' in data) { const vendor = data as VendorHome; return <Screen>
    <Hero eyebrow="Vendor dashboard" title={account.business_name || account.name} subtitle="Your event schedule, admission, and business profile in one place." />
    <View style={styles.stats}>{[['Tickets', vendor.stats.tickets], ['Upcoming', vendor.stats.upcoming_events], ['Profile', `${vendor.stats.profile_percent}%`]].map(([label, value]) => <Card key={String(label)} style={styles.stat}><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></Card>)}</View>
    <SectionTitle title="Upcoming events" />
    {vendor.upcoming_events.length ? vendor.upcoming_events.map(event => <EventRow key={event.id} event={event} />) : <Empty title="No vendor events yet" detail="Use More to find an event and purchase vendor admission." />}
  </Screen>; }
  if (account.type === 'admin' && data && 'stats' in data) { const admin = data as AdminHome; return <Screen>
    <Hero eyebrow="Enterprise administration" title={`Welcome, ${account.name.split(' ')[0]}`} subtitle="A live view of the TrackOps network." />
    <View style={styles.adminStats}>{[['Tracks', admin.stats.tracks], ['Staff', admin.stats.staff], ['Drivers', admin.stats.drivers], ['Vendors', admin.stats.vendors]].map(([label, value]) => <Card key={String(label)} style={styles.adminStat}><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></Card>)}</View>
    <Pressable style={styles.scanAction} onPress={() => router.push('/(tabs)/more')}><View style={{ flex: 1 }}><Text style={styles.scanTitle}>Open enterprise tools</Text><Text style={styles.scanDetail}>Tracks, accounts, orders, RFID fulfillment, and settings.</Text></View><Text style={styles.arrow}>›</Text></Pressable>
  </Screen>; }
  return <Screen><Hero eyebrow={account.type} title={`Welcome, ${account.name}`} />{error ? <Empty title="Unable to load dashboard" detail={error} /> : null}</Screen>;
}

function EventRow({ event }: { event: TrackEvent }) { return <Pressable onPress={() => router.push(`/event/${event.id}`)}><Card style={styles.event}><View style={{ flex: 1 }}><Text style={ui.title}>{event.name}</Text><Text style={ui.body}>{eventDate(event.date)} · {event.track.name}</Text></View><Text style={styles.arrow}>›</Text></Card></Pressable>; }
const styles = StyleSheet.create({ stats: { flexDirection: 'row', gap: 9 }, stat: { flex: 1, alignItems: 'center', paddingHorizontal: 4 }, adminStats: { flexDirection: 'row', flexWrap: 'wrap', gap: 9 }, adminStat: { width: '48%', alignItems: 'center' }, statValue: { color: palette.ink, fontSize: 23, fontWeight: '900' }, statLabel: { color: palette.muted, fontSize: 11, fontWeight: '700', marginTop: 2 }, event: { flexDirection: 'row', alignItems: 'center', gap: 12 }, arrow: { color: palette.orange, fontSize: 30, fontWeight: '400' }, scanAction: { backgroundColor: palette.orange, borderRadius: 19, padding: 17, flexDirection: 'row', alignItems: 'center', gap: 13 }, scanIcon: { color: 'white', fontSize: 32 }, scanTitle: { color: 'white', fontSize: 17, fontWeight: '900' }, scanDetail: { color: '#FFEDD5', fontSize: 13, marginTop: 3 } });
