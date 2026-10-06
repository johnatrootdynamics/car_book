import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { DriverSpaceSwitch, type DriverSpace } from '@/components/DriverSpaceSwitch';
import { Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';
import { CommunityExperience } from './community';

type DriverHome = { stats: { events_attended: number; upcoming_events: number; tracks_visited: number; vehicles: number }; upcoming_events: TrackEvent[] };
type StaffHome = { stats: { upcoming_events: number; upcoming_drivers: number }; events: TrackEvent[] };
type VendorHome = { stats: { tickets: number; upcoming_events: number; profile_percent: number }; upcoming_events: TrackEvent[] };
type AdminHome = { stats: { tracks: number; staff: number; drivers: number; vendors: number } };

export default function HomeScreen() {
  const { account, api } = useAuth(); const [data, setData] = useState<DriverHome | StaffHome | VendorHome | AdminHome | null>(null); const [error, setError] = useState('');
  const [driverSpace, setDriverSpace] = useState<DriverSpace>('track');
  useFocusEffect(useCallback(() => { if (!account) return; setData(null); setError(''); const path = account.type === 'user' ? '/driver/dashboard' : account.type === 'employee' ? '/staff/dashboard' : account.type === 'vendor' ? '/vendor/dashboard' : '/admin/dashboard'; api<any>(path).then(setData).catch(e => setError(e.message)); }, [account, api]));
  if (!account || (!data && !error)) return <Loading />;
  if (account.type === 'user' && data && 'stats' in data) {
    if (driverSpace === 'social') return <CommunityExperience onShowTrack={() => setDriverSpace('track')} />;
    return <DriverDashboard name={account.name} data={data as DriverHome} onShowSocial={() => setDriverSpace('social')} />;
  }
  if (account.type === 'employee' && data && 'events' in data) { const staff = data as StaffHome; const stats = staff.stats || { upcoming_events: staff.events.length, upcoming_drivers: 0 }; return <Screen>
    <Hero eyebrow={account.role === 'office_staff' ? 'Office staff' : 'Track staff'} title={account.track_name || 'Track operations'} subtitle="Fast access to the tools you use at the gate." />
    <View style={styles.stats}>{[['Events', stats.upcoming_events], ['Drivers', stats.upcoming_drivers]].map(([label, value]) => <Card key={String(label)} style={styles.stat}><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></Card>)}</View>
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

function DriverDashboard({ name, data, onShowSocial }: { name: string; data: DriverHome; onShowSocial: () => void }) {
  const nextEvent = data.upcoming_events[0];
  const firstName = name.trim().split(/\s+/)[0] || 'Driver';
  const greetingName = `${firstName.charAt(0).toUpperCase()}${firstName.slice(1)}`;
  return <Screen>
    <DriverSpaceSwitch active="track" onChange={space => space === 'social' && onShowSocial()} />
    <View style={styles.driverHero}>
      <Text style={styles.driverEyebrow}>DRIVER DASHBOARD</Text>
      <Text style={styles.driverWelcome}>Welcome back, {greetingName}</Text>
      <View style={styles.driverStats}>
        <DriverStat value={data.stats.events_attended} label="Track days" />
        <View style={styles.statDivider} />
        <DriverStat value={data.stats.tracks_visited} label="Tracks" />
        <View style={styles.statDivider} />
        <DriverStat value={data.stats.vehicles} label="Cars" />
      </View>
    </View>

    <SectionTitle title="Next up" />
    {nextEvent ? <Pressable onPress={() => router.push(`/event/${nextEvent.id}`)} style={({ pressed }) => pressed && styles.pressed}>
      <Card style={styles.nextEvent}>
        <View style={styles.dateBadge}><Text style={styles.dateDay}>{new Date(`${nextEvent.date}T12:00:00`).getDate()}</Text><Text style={styles.dateMonth}>{new Date(`${nextEvent.date}T12:00:00`).toLocaleString('en-US', { month: 'short' }).toUpperCase()}</Text></View>
        <View style={styles.nextEventCopy}><Text style={styles.nextLabel}>BOOKED EVENT</Text><Text style={styles.nextEventName}>{nextEvent.name}</Text><Text style={styles.nextEventDetail}>{eventDate(nextEvent.date)} · {nextEvent.track.name}</Text></View>
        <Text style={styles.arrow}>›</Text>
      </Card>
      {data.upcoming_events.length > 1 ? <Text style={styles.moreEvents}>+{data.upcoming_events.length - 1} more booked event{data.upcoming_events.length === 2 ? '' : 's'}</Text> : null}
    </Pressable> : <Card style={styles.compactEmpty}><Text style={styles.compactEmptyTitle}>Nothing booked yet</Text><Text style={styles.compactEmptyDetail}>Your next booked track day will appear here.</Text></Card>}

  </Screen>;
}

function DriverStat({ value, label }: { value: number; label: string }) {
  return <View style={styles.driverStat}><Text style={styles.driverStatValue}>{value}</Text><Text style={styles.driverStatLabel}>{label}</Text></View>;
}

function EventRow({ event }: { event: TrackEvent }) { return <Pressable onPress={() => router.push(`/event/${event.id}`)}><Card style={styles.event}><View style={{ flex: 1 }}><Text style={ui.title}>{event.name}</Text><Text style={ui.body}>{eventDate(event.date)} · {event.track.name}</Text></View><Text style={styles.arrow}>›</Text></Card></Pressable>; }
const styles = StyleSheet.create({
  driverHero: { backgroundColor: palette.navy, borderRadius: 24, padding: 20, gap: 5 },
  driverEyebrow: { color: '#FDBA74', fontSize: 10, fontWeight: '900', letterSpacing: 1.25 },
  driverWelcome: { color: 'white', fontSize: 27, lineHeight: 32, fontWeight: '900' },
  driverStats: { flexDirection: 'row', alignItems: 'center', marginTop: 14, paddingTop: 14, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,.14)' },
  driverStat: { flex: 1, alignItems: 'center' }, driverStatValue: { color: 'white', fontSize: 19, fontWeight: '900' }, driverStatLabel: { color: '#D0D5DD', fontSize: 10, fontWeight: '700', marginTop: 2 }, statDivider: { width: 1, height: 27, backgroundColor: 'rgba(255,255,255,.16)' },
  pressed: { opacity: .62 },
  nextEvent: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14 }, dateBadge: { width: 54, height: 58, borderRadius: 14, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' }, dateDay: { color: palette.orange, fontSize: 21, fontWeight: '900' }, dateMonth: { color: '#C2410C', fontSize: 9, fontWeight: '900' }, nextEventCopy: { flex: 1 }, nextLabel: { color: palette.orange, fontSize: 9, fontWeight: '900', letterSpacing: .8 }, nextEventName: { color: palette.ink, fontSize: 17, lineHeight: 21, fontWeight: '900', marginTop: 3 }, nextEventDetail: { color: palette.muted, fontSize: 11, lineHeight: 16, marginTop: 3 }, moreEvents: { color: palette.muted, fontSize: 11, fontWeight: '700', textAlign: 'center', marginTop: 8 },
  compactEmpty: { padding: 14 }, compactEmptyTitle: { color: palette.ink, fontSize: 14, fontWeight: '900' }, compactEmptyDetail: { color: palette.muted, fontSize: 11, lineHeight: 16, marginTop: 3 },
  stats: { flexDirection: 'row', gap: 9 }, stat: { flex: 1, alignItems: 'center', paddingHorizontal: 4 }, adminStats: { flexDirection: 'row', flexWrap: 'wrap', gap: 9 }, adminStat: { width: '48%', alignItems: 'center' }, statValue: { color: palette.ink, fontSize: 23, fontWeight: '900' }, statLabel: { color: palette.muted, fontSize: 11, fontWeight: '700', marginTop: 2 }, event: { flexDirection: 'row', alignItems: 'center', gap: 12 }, arrow: { color: palette.orange, fontSize: 30, fontWeight: '400' }, scanAction: { backgroundColor: palette.orange, borderRadius: 19, padding: 17, flexDirection: 'row', alignItems: 'center', gap: 13 }, scanTitle: { color: 'white', fontSize: 17, fontWeight: '900' }, scanDetail: { color: '#FFEDD5', fontSize: 13, marginTop: 3 },
});
