import { SymbolView } from 'expo-symbols';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
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
  useFocusEffect(useCallback(() => { if (!account) return; setData(null); setError(''); const path = account.type === 'user' ? '/driver/dashboard' : account.type === 'employee' ? '/staff/dashboard' : account.type === 'vendor' ? '/vendor/dashboard' : '/admin/dashboard'; api<any>(path).then(setData).catch(e => setError(e.message)); }, [account, api]));
  if (!account || (!data && !error)) return <Loading />;
  if (account.type === 'user' && data && 'stats' in data) return <DriverDashboard name={account.name} data={data as DriverHome} />;
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

const driverActions = [
  { title: 'Find events', detail: 'Book a track day', symbol: 'calendar.badge.plus', route: '/(tabs)/events' },
  { title: 'My tickets', detail: 'Open your QR', symbol: 'qrcode', route: '/(tabs)/tickets' },
  { title: 'Add a car', detail: 'Build your garage', symbol: 'car.fill', route: '/car/new' },
  { title: 'RFID tags', detail: 'Order or activate', symbol: 'wave.3.right', route: '/rfid' },
];

function DriverDashboard({ name, data }: { name: string; data: DriverHome }) {
  const nextEvent = data.upcoming_events[0];
  const firstName = name.trim().split(/\s+/)[0] || 'Driver';
  const greetingName = `${firstName.charAt(0).toUpperCase()}${firstName.slice(1)}`;
  return <Screen>
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

    <View style={styles.quickGrid}>
      {driverActions.map(action => <Pressable key={action.title} onPress={() => router.push(action.route as never)} style={({ pressed }) => [styles.quickAction, pressed && styles.pressed]}>
        <View style={styles.quickIcon}><SymbolView name={{ ios: action.symbol, android: action.symbol, web: action.symbol } as any} tintColor={palette.orange} size={21} /></View>
        <View style={styles.quickCopy}><Text style={styles.quickTitle}>{action.title}</Text><Text style={styles.quickDetail}>{action.detail}</Text></View>
        <Text style={styles.quickArrow}>›</Text>
      </Pressable>)}
    </View>

    <SectionTitle title="Next up" action={<Pressable onPress={() => router.push('/(tabs)/events')}><Text style={styles.sectionAction}>View all</Text></Pressable>} />
    {nextEvent ? <Pressable onPress={() => router.push(`/event/${nextEvent.id}`)} style={({ pressed }) => pressed && styles.pressed}>
      <Card style={styles.nextEvent}>
        <View style={styles.dateBadge}><Text style={styles.dateDay}>{new Date(`${nextEvent.date}T12:00:00`).getDate()}</Text><Text style={styles.dateMonth}>{new Date(`${nextEvent.date}T12:00:00`).toLocaleString('en-US', { month: 'short' }).toUpperCase()}</Text></View>
        <View style={styles.nextEventCopy}><Text style={styles.nextLabel}>BOOKED EVENT</Text><Text style={styles.nextEventName}>{nextEvent.name}</Text><Text style={styles.nextEventDetail}>{eventDate(nextEvent.date)} · {nextEvent.track.name}</Text></View>
        <Text style={styles.arrow}>›</Text>
      </Card>
      {data.upcoming_events.length > 1 ? <Text style={styles.moreEvents}>+{data.upcoming_events.length - 1} more booked event{data.upcoming_events.length === 2 ? '' : 's'}</Text> : null}
    </Pressable> : <CompactEmpty title="Nothing booked yet" detail="Find an event when you’re ready for the next track day." action="Browse events" onPress={() => router.push('/(tabs)/events')} />}

    <SectionTitle title="Your garage" action={<Pressable onPress={() => router.push('/(tabs)/garage')}><Text style={styles.sectionAction}>Manage</Text></Pressable>} />
    {data.garage.length ? <Card style={styles.garageList}>{data.garage.slice(0, 2).map((car, index) => <Pressable key={car.id} onPress={() => router.push(`/car/${car.id}`)} style={({ pressed }) => [styles.garageRow, index > 0 && styles.rowDivider, pressed && styles.pressed]}>
      <View style={styles.carBadge}><Text style={styles.carLetters}>{car.make.slice(0, 1)}{car.model.slice(0, 1)}</Text></View>
      <View style={{ flex: 1 }}><Text style={styles.carName}>{car.label}</Text><Text style={styles.carDetail}>{car.color || 'Color not listed'}</Text></View>
      <Text style={styles.arrow}>›</Text>
    </Pressable>)}</Card> : <CompactEmpty title="No cars yet" detail="Add a car once, then choose it during checkout." action="Add a car" onPress={() => router.push('/car/new')} />}
  </Screen>;
}

function DriverStat({ value, label }: { value: number; label: string }) {
  return <View style={styles.driverStat}><Text style={styles.driverStatValue}>{value}</Text><Text style={styles.driverStatLabel}>{label}</Text></View>;
}

function CompactEmpty({ title, detail, action, onPress }: { title: string; detail: string; action: string; onPress: () => void }) {
  return <Card style={styles.compactEmpty}><View style={{ flex: 1 }}><Text style={styles.compactEmptyTitle}>{title}</Text><Text style={styles.compactEmptyDetail}>{detail}</Text></View><Pressable onPress={onPress} style={styles.compactEmptyAction}><Text style={styles.compactEmptyActionText}>{action}</Text></Pressable></Card>;
}

function EventRow({ event }: { event: TrackEvent }) { return <Pressable onPress={() => router.push(`/event/${event.id}`)}><Card style={styles.event}><View style={{ flex: 1 }}><Text style={ui.title}>{event.name}</Text><Text style={ui.body}>{eventDate(event.date)} · {event.track.name}</Text></View><Text style={styles.arrow}>›</Text></Card></Pressable>; }
const styles = StyleSheet.create({
  driverHero: { backgroundColor: palette.navy, borderRadius: 24, padding: 20, gap: 5 },
  driverEyebrow: { color: '#FDBA74', fontSize: 10, fontWeight: '900', letterSpacing: 1.25 },
  driverWelcome: { color: 'white', fontSize: 27, lineHeight: 32, fontWeight: '900' },
  driverStats: { flexDirection: 'row', alignItems: 'center', marginTop: 14, paddingTop: 14, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,.14)' },
  driverStat: { flex: 1, alignItems: 'center' }, driverStatValue: { color: 'white', fontSize: 19, fontWeight: '900' }, driverStatLabel: { color: '#D0D5DD', fontSize: 10, fontWeight: '700', marginTop: 2 }, statDivider: { width: 1, height: 27, backgroundColor: 'rgba(255,255,255,.16)' },
  quickGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 9 },
  quickAction: { width: '48.6%', minHeight: 80, padding: 12, borderRadius: 17, borderWidth: 1, borderColor: palette.line, backgroundColor: 'white', flexDirection: 'row', alignItems: 'center', gap: 9 },
  quickIcon: { width: 38, height: 38, borderRadius: 12, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' }, quickCopy: { flex: 1 }, quickTitle: { color: palette.ink, fontSize: 13, fontWeight: '900' }, quickDetail: { color: palette.muted, fontSize: 10, lineHeight: 14, marginTop: 2 }, quickArrow: { color: palette.orange, fontSize: 22 }, pressed: { opacity: .62 },
  sectionAction: { color: palette.orange, fontSize: 12, fontWeight: '900' },
  nextEvent: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14 }, dateBadge: { width: 54, height: 58, borderRadius: 14, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' }, dateDay: { color: palette.orange, fontSize: 21, fontWeight: '900' }, dateMonth: { color: '#C2410C', fontSize: 9, fontWeight: '900' }, nextEventCopy: { flex: 1 }, nextLabel: { color: palette.orange, fontSize: 9, fontWeight: '900', letterSpacing: .8 }, nextEventName: { color: palette.ink, fontSize: 17, lineHeight: 21, fontWeight: '900', marginTop: 3 }, nextEventDetail: { color: palette.muted, fontSize: 11, lineHeight: 16, marginTop: 3 }, moreEvents: { color: palette.muted, fontSize: 11, fontWeight: '700', textAlign: 'center', marginTop: 8 },
  garageList: { paddingVertical: 2, paddingHorizontal: 14 }, garageRow: { minHeight: 72, flexDirection: 'row', alignItems: 'center', gap: 11, paddingVertical: 11 }, rowDivider: { borderTopWidth: 1, borderTopColor: palette.line }, carBadge: { width: 44, height: 44, borderRadius: 13, backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center' }, carLetters: { color: 'white', fontSize: 13, fontWeight: '900' }, carName: { color: palette.ink, fontSize: 14, fontWeight: '900' }, carDetail: { color: palette.muted, fontSize: 11, marginTop: 3 },
  compactEmpty: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14 }, compactEmptyTitle: { color: palette.ink, fontSize: 14, fontWeight: '900' }, compactEmptyDetail: { color: palette.muted, fontSize: 11, lineHeight: 16, marginTop: 3 }, compactEmptyAction: { borderRadius: 10, backgroundColor: palette.orange, paddingHorizontal: 11, paddingVertical: 9 }, compactEmptyActionText: { color: 'white', fontSize: 11, fontWeight: '900' },
  stats: { flexDirection: 'row', gap: 9 }, stat: { flex: 1, alignItems: 'center', paddingHorizontal: 4 }, adminStats: { flexDirection: 'row', flexWrap: 'wrap', gap: 9 }, adminStat: { width: '48%', alignItems: 'center' }, statValue: { color: palette.ink, fontSize: 23, fontWeight: '900' }, statLabel: { color: palette.muted, fontSize: 11, fontWeight: '700', marginTop: 2 }, event: { flexDirection: 'row', alignItems: 'center', gap: 12 }, arrow: { color: palette.orange, fontSize: 30, fontWeight: '400' }, scanAction: { backgroundColor: palette.orange, borderRadius: 19, padding: 17, flexDirection: 'row', alignItems: 'center', gap: 13 }, scanTitle: { color: 'white', fontSize: 17, fontWeight: '900' }, scanDetail: { color: '#FFEDD5', fontSize: 13, marginTop: 3 },
});
