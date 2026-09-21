import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Image, Modal, Pressable, StyleSheet, Switch, Text, View } from 'react-native';

import { Button, Card, Empty, Field, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate, money } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type Action = 'general' | 'participants' | 'schedule' | 'lanes' | 'live' | 'history' | 'analytics';
type General = {
  name: string; date: string; start_time: string; end_time: string;
  driver_price: number; spectator_price: number; vendor_price: number;
  driver_capacity: number; spectator_capacity: number; vendor_capacity: number;
  run_voting_enabled: boolean; thumbnail_url?: string | null;
  layout: Layout; layouts: Layout[];
};
type Layout = { id: number | null; name: string; image_url?: string | null };
type Participant = {
  registration_id: number; user_id: number; name: string; email: string;
  car: { id: number; label: string }; driver_class: string; checked_in_at?: string | null;
  waiver_status: 'signed' | 'not_required' | 'missing';
  inspection_status: 'passed' | 'needs_attention' | 'not_started';
};
type Slot = { id: number; class_code: string; start_time: string; end_time: string };
type Lane = { id: number; name: string; description: string };
type RunParticipant = {
  car_id: number; car: { label: string; color?: string | null }; driver_id: number;
  driver: string; driver_initials: string; driver_image_url?: string | null;
  car_image_url?: string | null; entered_at: string; exited_at?: string | null;
};
type Run = {
  id: number; status?: string; started_at: string; ended_at?: string | null;
  participants: RunParticipant[]; votes?: { up: number; down: number };
  videos?: { id: number; name: string; source_key: string; status: string; url?: string | null }[];
};
type LiveCar = RunParticipant & { scanner?: string | null; eligible: boolean; eligibility_reason?: string | null };
type OperationData = {
  event: TrackEvent;
  general?: General;
  participants?: Participant[];
  schedule?: { start_time?: string | null; end_time?: string | null; classes: string[]; can_edit: boolean; slots: Slot[] };
  lanes?: Lane[];
  live?: { count: number; cars: LiveCar[]; runs: Run[] };
  history?: { runs: Run[] };
  analytics?: { total_signups: number; checked_in: number; signup_trend: { day: string; count: number }[]; class_counts: { class_code: string; count: number }[] };
};

const actionCopy: Record<Action, { eyebrow: string; title: string; subtitle: string }> = {
  general: { eyebrow: 'Event setup', title: 'General & pricing', subtitle: 'Details, admission, capacity, layout, and audience voting.' },
  participants: { eyebrow: 'Event roster', title: 'Participants', subtitle: 'Driver, waiver, check-in, and inspection status in one place.' },
  schedule: { eyebrow: 'Track plan', title: 'Schedule', subtitle: 'Class run windows for this event.' },
  lanes: { eyebrow: 'Staging', title: 'Lineup lanes', subtitle: 'Publish the order and instructions drivers see before track entry.' },
  live: { eyebrow: 'Live operations', title: 'Cars on track', subtitle: 'Automatically refreshes while this screen is open.' },
  history: { eyebrow: 'Event archive', title: 'Run history', subtitle: 'Saved runs, drivers, audience votes, and videos.' },
  analytics: { eyebrow: 'Event performance', title: 'Analytics', subtitle: 'Registration activity and driver class distribution.' },
};

export default function EventOperationScreen() {
  const params = useLocalSearchParams<{ id: string; action: string }>();
  const action = params.action as Action;
  const { api } = useAuth();
  const [data, setData] = useState<OperationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const validAction = Object.prototype.hasOwnProperty.call(actionCopy, action);

  const load = useCallback(async (silent = false) => {
    if (!validAction) return;
    if (!silent) setLoading(true);
    setError('');
    try {
      const body = await api<OperationData>(`/staff/events/${params.id}/operations/${action}`);
      setData(body);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load this event tool.');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [action, api, params.id, validAction]);

  useFocusEffect(useCallback(() => {
    load();
    if (action !== 'live') return undefined;
    const timer = setInterval(() => load(true), 2000);
    return () => clearInterval(timer);
  }, [action, load]));

  if (!validAction) return <Screen><Empty title="Event tool unavailable" detail="That event action is not available in this app." /></Screen>;
  if (loading && !data) return <Loading />;
  if (!data) return <Screen><Empty title="Unable to load event tool" detail={error || 'Try again in a moment.'} /><Button title="Try again" onPress={() => load()} /></Screen>;
  const copy = actionCopy[action];

  return <Screen>
    <View style={styles.heading}>
      <Text style={styles.eyebrow}>{copy.eyebrow.toUpperCase()}</Text>
      <Text style={styles.title}>{copy.title}</Text>
      <Text style={styles.eventName}>{data.event.name} · {eventDate(data.event.date)}</Text>
      <Text style={styles.subtitle}>{copy.subtitle}</Text>
    </View>
    {error ? <Notice tone="error" text={error} /> : null}
    {action === 'general' && data.general ? <GeneralPanel eventId={params.id} data={data} onData={setData} /> : null}
    {action === 'participants' && data.participants ? <ParticipantsPanel eventId={params.id} data={data} onData={setData} /> : null}
    {action === 'schedule' && data.schedule ? <SchedulePanel eventId={params.id} data={data} onData={setData} /> : null}
    {action === 'lanes' && data.lanes ? <LanesPanel eventId={params.id} data={data} onData={setData} /> : null}
    {action === 'live' && data.live ? <LivePanel data={data} /> : null}
    {action === 'history' && data.history ? <HistoryPanel data={data} /> : null}
    {action === 'analytics' && data.analytics ? <AnalyticsPanel data={data} /> : null}
  </Screen>;
}

function GeneralPanel({ eventId, data, onData }: PanelProps) {
  const { api } = useAuth();
  const general = data.general!;
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState(() => generalForm(general));
  useEffect(() => setForm(generalForm(general)), [general]);
  const update = (key: keyof typeof form, value: string | boolean | number | null) => setForm(current => ({ ...current, [key]: value }));
  const save = async () => {
    setSaving(true); setError('');
    try {
      const body = await api<OperationData>(`/staff/events/${eventId}/operations/general`, { method: 'PATCH', body: JSON.stringify(form) });
      onData(body); setEditing(false);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to save event.'); }
    finally { setSaving(false); }
  };
  if (editing) return <>
    <Card style={styles.formCard}>
      <LabeledField label="Event name" value={String(form.name)} onChangeText={value => update('name', value)} />
      <LabeledField label="Date · YYYY-MM-DD" value={String(form.date)} onChangeText={value => update('date', value)} autoCapitalize="none" />
      <View style={styles.twoColumn}><View style={styles.column}><LabeledField label="Start · HH:MM" value={String(form.start_time)} onChangeText={value => update('start_time', value)} autoCapitalize="none" /></View><View style={styles.column}><LabeledField label="End · HH:MM" value={String(form.end_time)} onChangeText={value => update('end_time', value)} autoCapitalize="none" /></View></View>
      <SectionTitle title="Admission pricing" />
      <View style={styles.twoColumn}><View style={styles.column}><LabeledField label="Driver" value={String(form.driver_price)} onChangeText={value => update('driver_price', value)} keyboardType="decimal-pad" /></View><View style={styles.column}><LabeledField label="Spectator" value={String(form.spectator_price)} onChangeText={value => update('spectator_price', value)} keyboardType="decimal-pad" /></View></View>
      <LabeledField label="Vendor representative" value={String(form.vendor_price)} onChangeText={value => update('vendor_price', value)} keyboardType="decimal-pad" />
      <SectionTitle title="Ticket limits" />
      <Text style={styles.hint}>Use 0 for unlimited.</Text>
      <View style={styles.twoColumn}><View style={styles.column}><LabeledField label="Drivers" value={String(form.driver_capacity)} onChangeText={value => update('driver_capacity', value)} keyboardType="number-pad" /></View><View style={styles.column}><LabeledField label="Spectators" value={String(form.spectator_capacity)} onChangeText={value => update('spectator_capacity', value)} keyboardType="number-pad" /></View></View>
      <LabeledField label="Vendor representatives" value={String(form.vendor_capacity)} onChangeText={value => update('vendor_capacity', value)} keyboardType="number-pad" />
      <SectionTitle title="Track layout" />
      <View style={styles.choices}>{[{ id: null, name: 'Default' }, ...general.layouts].map(layout => <Choice key={layout.id ?? 'default'} label={layout.name} selected={form.layout_id === layout.id} onPress={() => update('layout_id', layout.id)} />)}</View>
      <View style={styles.switchRow}><View style={{ flex: 1 }}><Text style={styles.cardTitle}>Audience run voting</Text><Text style={ui.body}>Ticketed attendees can rate each run once.</Text></View><Switch value={Boolean(form.run_voting_enabled)} onValueChange={value => update('run_voting_enabled', value)} trackColor={{ false: '#D0D5DD', true: '#FDBA74' }} thumbColor={form.run_voting_enabled ? palette.orange : '#F2F4F7'} /></View>
    </Card>
    {error ? <Notice tone="error" text={error} /> : null}
    <Button title={saving ? 'Saving event…' : 'Save event'} onPress={save} disabled={saving} />
    <Button title="Cancel" tone="secondary" onPress={() => { setForm(generalForm(general)); setEditing(false); setError(''); }} disabled={saving} />
  </>;
  return <>
    <Card style={styles.summaryCard}>
      <View style={ui.between}><Text style={styles.cardTitle}>{general.name}</Text>{data.event.type === 'private' ? <Pill text="Private rental" tone="neutral" /> : <Pressable onPress={() => setEditing(true)}><Text style={styles.actionText}>Edit</Text></Pressable>}</View>
      <DetailRow label="Date" value={eventDate(general.date)} />
      <DetailRow label="Time" value={`${clockLabel(general.start_time)} – ${clockLabel(general.end_time)}`} />
      <DetailRow label="Layout" value={general.layout.name} />
      <DetailRow label="Run voting" value={general.run_voting_enabled ? 'Enabled' : 'Off'} />
      {general.layout.image_url ? <Image source={{ uri: general.layout.image_url }} style={styles.layoutImage} /> : null}
    </Card>
    <SectionTitle title="Admission & capacity" />
    <View style={styles.statGrid}>
      <Stat label="Driver" value={money(general.driver_price)} detail={capacityLabel(general.driver_capacity, data.event.availability?.driver)} />
      <Stat label="Spectator" value={money(general.spectator_price)} detail={capacityLabel(general.spectator_capacity, data.event.availability?.spectator)} />
      <Stat label="Vendor" value={money(general.vendor_price)} detail={capacityLabel(general.vendor_capacity, data.event.availability?.vendor)} />
    </View>
  </>;
}

function ParticipantsPanel({ eventId, data, onData }: PanelProps) {
  const { api } = useAuth();
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState('');
  const participants = useMemo(() => data.participants!.filter(item => `${item.name} ${item.email} ${item.car.label}`.toLowerCase().includes(query.trim().toLowerCase())), [data.participants, query]);
  const checkIn = async (participant: Participant) => {
    setBusy(participant.registration_id); setError('');
    try {
      const body = await api<OperationData>(`/staff/events/${eventId}/participants/${participant.registration_id}/check-in`, { method: 'POST' });
      onData(body);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to check in driver.'); }
    finally { setBusy(null); }
  };
  return <>
    <Field placeholder="Search name, email, or vehicle" value={query} onChangeText={setQuery} autoCapitalize="none" autoCorrect={false} />
    <Text style={styles.resultCount}>{participants.length} of {data.participants!.length} drivers</Text>
    {error ? <Notice tone="error" text={error} /> : null}
    {participants.length ? participants.map(participant => {
      const waiverReady = ['signed', 'not_required'].includes(participant.waiver_status);
      return <Card key={participant.registration_id} style={styles.personCard}>
        <Pressable onPress={() => router.push({ pathname: '/staff/driver/[id]', params: { id: String(participant.user_id) } })} style={styles.personHead}>
          <Avatar label={participant.name} />
          <View style={{ flex: 1 }}><View style={ui.between}><Text style={styles.personName}>{participant.name}</Text><Pill text={`Class ${participant.driver_class}`} tone="neutral" /></View><Text style={ui.body}>{participant.car.label}</Text><Text style={styles.personEmail}>{participant.email}</Text></View>
          <Text style={styles.arrow}>›</Text>
        </Pressable>
        <View style={styles.statusLine}><Pill text={participant.checked_in_at ? '✓ Checked in' : waiverReady ? 'Ready to check in' : 'Waiver needed'} tone={participant.checked_in_at ? 'success' : waiverReady ? 'neutral' : 'danger'} /><Pill text={inspectionLabel(participant.inspection_status)} tone={participant.inspection_status === 'passed' ? 'success' : participant.inspection_status === 'needs_attention' ? 'danger' : 'neutral'} /></View>
        {!participant.checked_in_at ? <Button title={busy === participant.registration_id ? 'Checking in…' : waiverReady ? 'Check in driver' : 'Waiver required'} onPress={() => checkIn(participant)} disabled={!waiverReady || busy !== null} /> : <Button title={participant.inspection_status === 'not_started' ? 'Inspect vehicle' : 'Review inspection'} tone="secondary" onPress={() => router.push(`/inspection/${participant.registration_id}`)} />}
      </Card>;
    }) : <Empty title="No matching drivers" detail="Try a different name, email, or vehicle." />}
  </>;
}

function SchedulePanel({ eventId, data, onData }: PanelProps) {
  const { api } = useAuth();
  const schedule = data.schedule!;
  const [editing, setEditing] = useState<Slot | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ class_code: schedule.classes[0] || '', start_time: schedule.start_time || '', end_time: schedule.end_time || '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const openForm = (slot?: Slot) => { setEditing(slot || null); setForm(slot ? { class_code: slot.class_code, start_time: slot.start_time, end_time: slot.end_time } : { class_code: schedule.classes[0] || '', start_time: schedule.start_time || '', end_time: schedule.end_time || '' }); setShowForm(true); setError(''); };
  const save = async () => {
    setBusy(true); setError('');
    try {
      const body = await api<OperationData>(`/staff/events/${eventId}/operations/schedule`, { method: 'POST', body: JSON.stringify({ ...form, slot_id: editing?.id }) });
      onData(body); setShowForm(false); setEditing(null);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to save schedule slot.'); }
    finally { setBusy(false); }
  };
  const remove = (slot: Slot) => Alert.alert('Delete schedule slot?', `Class ${slot.class_code} · ${clockLabel(slot.start_time)} – ${clockLabel(slot.end_time)}`, [{ text: 'Cancel', style: 'cancel' }, { text: 'Delete', style: 'destructive', onPress: async () => { setBusy(true); setError(''); try { const body = await api<OperationData>(`/staff/events/${eventId}/operations/schedule/${slot.id}`, { method: 'DELETE' }); onData(body); } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to delete slot.'); } finally { setBusy(false); } } }]);
  if (showForm) return <>
    <Card style={styles.formCard}>
      <Text style={styles.cardTitle}>{editing ? 'Edit class slot' : 'Add class slot'}</Text>
      <Text style={styles.hint}>Event window: {clockLabel(schedule.start_time)} – {clockLabel(schedule.end_time)}</Text>
      <Text style={ui.label}>Driver class</Text>
      <View style={styles.choices}>{schedule.classes.map(value => <Choice key={value} label={`Class ${value}`} selected={form.class_code === value} onPress={() => setForm(current => ({ ...current, class_code: value }))} />)}</View>
      <View style={styles.twoColumn}><View style={styles.column}><LabeledField label="Start · HH:MM" value={form.start_time} onChangeText={value => setForm(current => ({ ...current, start_time: value }))} autoCapitalize="none" /></View><View style={styles.column}><LabeledField label="End · HH:MM" value={form.end_time} onChangeText={value => setForm(current => ({ ...current, end_time: value }))} autoCapitalize="none" /></View></View>
    </Card>
    {error ? <Notice tone="error" text={error} /> : null}
    <Button title={busy ? 'Saving slot…' : 'Save slot'} onPress={save} disabled={busy} />
    <Button title="Cancel" tone="secondary" onPress={() => setShowForm(false)} disabled={busy} />
  </>;
  return <>
    <Card style={styles.windowCard}><Text style={styles.smallCaps}>EVENT WINDOW</Text><Text style={styles.windowTime}>{clockLabel(schedule.start_time)} – {clockLabel(schedule.end_time)}</Text><Text style={ui.body}>{schedule.can_edit ? 'Office staff can edit the class plan.' : 'Read-only schedule set by office staff.'}</Text></Card>
    {error ? <Notice tone="error" text={error} /> : null}
    {schedule.classes.map(classCode => {
      const slots = schedule.slots.filter(slot => slot.class_code === classCode);
      return <Card key={classCode} style={styles.classCard}><View style={ui.between}><Pill text={`Class ${classCode}`} tone="neutral" /><Text style={styles.slotCount}>{slots.length ? `${slots.length} slot${slots.length === 1 ? '' : 's'}` : 'Not set'}</Text></View>{slots.map(slot => <View key={slot.id} style={styles.slotRow}><Text style={styles.slotTime}>{clockLabel(slot.start_time)} – {clockLabel(slot.end_time)}</Text>{schedule.can_edit ? <View style={styles.inlineActions}><Pressable onPress={() => openForm(slot)}><Text style={styles.actionText}>Edit</Text></Pressable><Pressable disabled={busy} onPress={() => remove(slot)}><Text style={styles.deleteText}>Delete</Text></Pressable></View> : null}</View>)}</Card>;
    })}
    {schedule.can_edit ? <Button title="Add schedule slot" onPress={() => openForm()} disabled={!schedule.start_time || !schedule.end_time || busy} /> : null}
  </>;
}

function LanesPanel({ eventId, data, onData }: PanelProps) {
  const { api } = useAuth();
  const [lanes, setLanes] = useState<Lane[]>(data.lanes!);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  useEffect(() => setLanes(data.lanes!), [data.lanes]);
  const change = (index: number, key: 'name' | 'description', value: string) => setLanes(current => current.map((lane, laneIndex) => laneIndex === index ? { ...lane, [key]: value } : lane));
  const move = (index: number, direction: -1 | 1) => setLanes(current => { const target = index + direction; if (target < 0 || target >= current.length) return current; const next = [...current]; [next[index], next[target]] = [next[target], next[index]]; return next; });
  const save = async () => { setBusy(true); setError(''); setNotice(''); try { const body = await api<OperationData>(`/staff/events/${eventId}/operations/lanes`, { method: 'PUT', body: JSON.stringify({ lanes }) }); onData(body); setNotice('Lineup lanes saved.'); } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to save lanes.'); } finally { setBusy(false); } };
  return <>
    {notice ? <Notice tone="success" text={notice} /> : null}{error ? <Notice tone="error" text={error} /> : null}
    {lanes.length ? lanes.map((lane, index) => <Card key={lane.id} style={styles.laneCard}><View style={styles.laneNumber}><Text style={styles.laneNumberText}>{index + 1}</Text></View><View style={{ flex: 1, gap: 9 }}><LabeledField label="Lane name" value={lane.name} maxLength={80} onChangeText={value => change(index, 'name', value)} placeholder="Beginner drivers" /><LabeledField label="Instructions" value={lane.description} maxLength={240} onChangeText={value => change(index, 'description', value)} placeholder="Optional staging landmark" /><View style={styles.inlineActions}><Pressable disabled={index === 0} onPress={() => move(index, -1)}><Text style={[styles.actionText, index === 0 && styles.disabledText]}>Move up</Text></Pressable><Pressable disabled={index === lanes.length - 1} onPress={() => move(index, 1)}><Text style={[styles.actionText, index === lanes.length - 1 && styles.disabledText]}>Move down</Text></Pressable><Pressable onPress={() => setLanes(current => current.filter((_, laneIndex) => laneIndex !== index))}><Text style={styles.deleteText}>Remove</Text></Pressable></View></View></Card>) : <Empty title="No lanes yet" detail="Add the first lane to publish staging directions." />}
    <Button tone="secondary" title="Add lane" onPress={() => setLanes(current => current.length >= 20 ? current : [...current, { id: -Date.now(), name: '', description: '' }])} disabled={lanes.length >= 20 || busy} />
    <Button title={busy ? 'Saving lanes…' : 'Save lineup lanes'} onPress={save} disabled={busy} />
  </>;
}

function LivePanel({ data }: { data: OperationData }) {
  const live = data.live!;
  return <>
    <Card style={styles.liveCount}><Text style={styles.liveNumber}>{live.count}</Text><Text style={styles.liveLabel}>{live.count === 1 ? 'car on track' : 'cars on track'}</Text><View style={styles.liveDot} /></Card>
    <SectionTitle title="On track now" />
    {live.cars.length ? live.cars.map(car => <Card key={car.car_id} style={[styles.liveCar, !car.eligible && styles.warningCard]}><Avatar label={car.driver} uri={car.driver_image_url} /><View style={{ flex: 1 }}><Text style={styles.personName}>{car.driver}</Text><Text style={ui.body}>{car.car.label}{car.car.color ? ` · ${car.car.color}` : ''}</Text><Text style={styles.personEmail}>Entered {dateTimeLabel(car.entered_at)}{car.scanner ? ` · ${car.scanner}` : ''}</Text>{!car.eligible ? <Text style={styles.warningText}>⚠ {car.eligibility_reason || 'Not eligible for track entry'}</Text> : null}</View></Card>) : <Empty title="Track is clear" detail="Activated cars appear here as soon as they enter." />}
    <SectionTitle title="Previous runs" />
    {live.runs.length ? live.runs.map((run, index) => <RunCard key={run.id} run={run} number={live.runs.length - index} compact />) : <Empty title="No completed runs" detail="Completed sessions will appear here automatically." />}
  </>;
}

function HistoryPanel({ data }: { data: OperationData }) {
  const [video, setVideo] = useState<{ url: string; title: string } | null>(null);
  const runs = data.history!.runs;
  return <>
    <Card style={styles.historySummary}><View><Text style={styles.smallCaps}>{eventDate(data.event.date)}</Text><Text style={styles.cardTitle}>{data.event.name}</Text></View><Text style={styles.historyCount}>{runs.length} run{runs.length === 1 ? '' : 's'}</Text></Card>
    {runs.length ? runs.map((run, index) => <RunCard key={run.id} run={run} number={runs.length - index} onVideo={(url, title) => setVideo({ url, title })} />) : <Empty title="No runs recorded" detail="Runs tied to this event will appear here." />}
    {video ? <RunVideo url={video.url} title={video.title} onClose={() => setVideo(null)} /> : null}
  </>;
}

function AnalyticsPanel({ data }: { data: OperationData }) {
  const analytics = data.analytics!;
  const classMax = Math.max(1, ...analytics.class_counts.map(item => item.count));
  const signupMax = Math.max(1, ...analytics.signup_trend.map(item => item.count));
  return <>
    <View style={styles.statGrid}><Stat label="Registrations" value={String(analytics.total_signups)} /><Stat label="Checked in" value={String(analytics.checked_in)} /><Stat label="Arrival rate" value={`${analytics.total_signups ? Math.round(analytics.checked_in / analytics.total_signups * 100) : 0}%`} /></View>
    <SectionTitle title="Driver classes" />
    <Card style={styles.chartCard}>{analytics.class_counts.map(item => <Bar key={item.class_code} label={`Class ${item.class_code}`} value={item.count} max={classMax} />)}</Card>
    <SectionTitle title="Signups over time" />
    {analytics.signup_trend.length ? <Card style={styles.chartCard}>{analytics.signup_trend.map(item => <Bar key={item.day} label={shortDate(item.day)} value={item.count} max={signupMax} />)}</Card> : <Empty title="No signups yet" detail="Registration activity will appear here." />}
  </>;
}

function RunCard({ run, number, compact = false, onVideo }: { run: Run; number: number; compact?: boolean; onVideo?: (url: string, title: string) => void }) {
  const readyVideos = (run.videos || []).filter(video => video.status === 'ready' && video.url);
  const splitVideos = readyVideos.filter(video => video.source_key === 'split-screen');
  const displayVideos = splitVideos.length ? splitVideos : readyVideos;
  return <Card style={styles.runCard}><View style={ui.between}><View><Text style={styles.smallCaps}>RUN {number}</Text><Text style={styles.runTime}>{dateTimeLabel(run.started_at)}{run.ended_at ? ` – ${dateTimeLabel(run.ended_at)}` : ' – Active'}</Text></View><Pill text={`${run.participants.length} driver${run.participants.length === 1 ? '' : 's'}`} tone="neutral" /></View>{run.votes ? <View style={styles.voteLine}><Text style={styles.voteUp}>👍 {run.votes.up}</Text><Text style={styles.voteDown}>👎 {run.votes.down}</Text></View> : null}{displayVideos.map(video => <Pressable key={video.id} onPress={() => onVideo?.(video.url!, `Run ${number} · ${video.name}`)} style={styles.videoButton}><SymbolView name={{ ios: 'play.circle.fill', android: 'play.circle.fill', web: 'play.circle.fill' } as any} tintColor={palette.orange} size={23} /><Text style={styles.videoText}>{video.name}</Text></Pressable>)}{!displayVideos.length && run.videos?.length ? <Text style={styles.videoStatus}>Video: {run.videos[0].status.replaceAll('_', ' ')}</Text> : null}<View style={styles.runDrivers}>{run.participants.map(participant => <View key={`${run.id}-${participant.car_id}`} style={styles.runDriver}><Avatar label={participant.driver} uri={participant.driver_image_url} small /><View style={{ flex: 1 }}><Text style={styles.driverName}>{participant.driver}</Text><Text style={styles.driverCar}>{participant.car.label}</Text>{!compact ? <Text style={styles.driverTimes}>In {dateTimeLabel(participant.entered_at)} · Out {participant.exited_at ? dateTimeLabel(participant.exited_at) : '—'}</Text> : null}</View></View>)}</View></Card>;
}

function RunVideo({ url, title, onClose }: { url: string; title: string; onClose: () => void }) {
  const player = useVideoPlayer(url, instance => instance.play());
  return <Modal visible animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}><View style={styles.videoModal}><View style={ui.between}><Text style={styles.videoTitle}>{title}</Text><Pressable onPress={onClose}><Text style={styles.actionText}>Done</Text></Pressable></View><VideoView player={player} style={styles.video} nativeControls contentFit="contain" fullscreenOptions={{ enable: true }} /></View></Modal>;
}

type PanelProps = { eventId: string; data: OperationData; onData: (data: OperationData) => void };
function generalForm(general: General) { return { name: general.name, date: general.date, start_time: general.start_time || '', end_time: general.end_time || '', driver_price: String(general.driver_price), spectator_price: String(general.spectator_price), vendor_price: String(general.vendor_price), driver_capacity: String(general.driver_capacity), spectator_capacity: String(general.spectator_capacity), vendor_capacity: String(general.vendor_capacity), layout_id: general.layout.id, run_voting_enabled: general.run_voting_enabled }; }
function Notice({ tone, text }: { tone: 'success' | 'error'; text: string }) { return <View style={[styles.notice, tone === 'success' ? styles.successNotice : styles.errorNotice]}><Text style={[styles.noticeText, tone === 'success' ? styles.successText : styles.errorText]}>{text}</Text></View>; }
function LabeledField({ label, ...props }: { label: string } & React.ComponentProps<typeof Field>) { return <View><Text style={ui.label}>{label}</Text><Field {...props} /></View>; }
function DetailRow({ label, value }: { label: string; value: string }) { return <View style={styles.detailRow}><Text style={ui.body}>{label}</Text><Text style={styles.detailValue}>{value}</Text></View>; }
function Choice({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) { return <Pressable onPress={onPress} style={[styles.choice, selected && styles.choiceSelected]}><Text style={[styles.choiceText, selected && styles.choiceTextSelected]}>{label}</Text></Pressable>; }
function Pill({ text, tone }: { text: string; tone: 'success' | 'danger' | 'neutral' }) { return <View style={[styles.pill, tone === 'success' ? styles.pillSuccess : tone === 'danger' ? styles.pillDanger : styles.pillNeutral]}><Text style={[styles.pillText, tone === 'success' ? styles.pillSuccessText : tone === 'danger' ? styles.pillDangerText : styles.pillNeutralText]}>{text}</Text></View>; }
function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) { return <Card style={styles.stat}><Text style={styles.statLabel}>{label}</Text><Text style={styles.statValue}>{value}</Text>{detail ? <Text style={styles.statDetail}>{detail}</Text> : null}</Card>; }
function Avatar({ label, uri, small = false }: { label: string; uri?: string | null; small?: boolean }) { const size = small ? styles.avatarSmall : null; return <View style={[styles.avatar, size]}>{uri ? <Image source={{ uri }} style={styles.avatarImage} /> : <Text style={[styles.avatarText, small && styles.avatarTextSmall]}>{initials(label)}</Text>}</View>; }
function Bar({ label, value, max }: { label: string; value: number; max: number }) { return <View style={styles.barRow}><View style={ui.between}><Text style={styles.barLabel}>{label}</Text><Text style={styles.barValue}>{value}</Text></View><View style={styles.barTrack}><View style={[styles.barFill, { width: `${Math.max(value ? 8 : 0, value / max * 100)}%` }]} /></View></View>; }
function initials(value: string) { return value.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase(); }
function clockLabel(value?: string | null) { if (!value) return 'Not set'; const [hourValue, minute = '00'] = value.slice(0, 5).split(':'); const hour = Number(hourValue); return `${hour % 12 || 12}:${minute} ${hour < 12 ? 'AM' : 'PM'}`; }
function dateTimeLabel(value: string) { const normalized = /Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`; return new Date(normalized).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' }); }
function shortDate(value: string) { return new Date(`${value}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }); }
function capacityLabel(capacity: number, availability?: { remaining?: number | null; unlimited?: boolean }) { return capacity === 0 || availability?.unlimited ? 'Unlimited' : `${availability?.remaining ?? capacity} of ${capacity} left`; }
function inspectionLabel(status: Participant['inspection_status']) { return status === 'passed' ? '✓ Inspection passed' : status === 'needs_attention' ? 'Inspection needs work' : 'Not inspected'; }

const styles = StyleSheet.create({
  heading: { gap: 4, paddingVertical: 3 }, eyebrow: { color: palette.orange, fontSize: 11, fontWeight: '900', letterSpacing: 1.2 }, title: { color: palette.ink, fontSize: 29, fontWeight: '900' }, eventName: { color: palette.ink, fontSize: 14, fontWeight: '800', marginTop: 2 }, subtitle: { color: palette.muted, fontSize: 14, lineHeight: 20, marginTop: 2 },
  notice: { borderRadius: 14, padding: 14 }, successNotice: { backgroundColor: palette.greenSoft }, errorNotice: { backgroundColor: palette.redSoft }, noticeText: { fontWeight: '800', lineHeight: 19 }, successText: { color: palette.green }, errorText: { color: palette.red },
  summaryCard: { gap: 2 }, cardTitle: { color: palette.ink, fontSize: 17, fontWeight: '900' }, actionText: { color: palette.orange, fontWeight: '900' }, deleteText: { color: palette.red, fontWeight: '900' }, disabledText: { color: '#D0D5DD' }, detailRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 15, paddingTop: 12, marginTop: 10, borderTopWidth: 1, borderTopColor: palette.line }, detailValue: { color: palette.ink, fontWeight: '800', textAlign: 'right', flexShrink: 1 }, layoutImage: { width: '100%', height: 180, borderRadius: 14, marginTop: 14, resizeMode: 'cover' },
  formCard: { gap: 14 }, twoColumn: { flexDirection: 'row', gap: 10 }, column: { flex: 1 }, hint: { color: palette.muted, fontSize: 12, lineHeight: 17 }, choices: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 }, choice: { borderWidth: 1, borderColor: palette.line, backgroundColor: 'white', borderRadius: 999, paddingHorizontal: 13, paddingVertical: 9 }, choiceSelected: { borderColor: palette.orange, backgroundColor: palette.orangeSoft }, choiceText: { color: palette.muted, fontWeight: '800' }, choiceTextSelected: { color: '#C2410C' }, switchRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingTop: 4 },
  statGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 9 }, stat: { flexGrow: 1, minWidth: '30%', padding: 14 }, statLabel: { color: palette.muted, fontSize: 11, fontWeight: '900', textTransform: 'uppercase', letterSpacing: .6 }, statValue: { color: palette.ink, fontSize: 21, fontWeight: '900', marginTop: 5 }, statDetail: { color: palette.muted, fontSize: 11, marginTop: 2 },
  resultCount: { color: palette.muted, fontSize: 12, fontWeight: '800' }, personCard: { gap: 13 }, personHead: { flexDirection: 'row', alignItems: 'center', gap: 11 }, personName: { color: palette.ink, fontSize: 16, fontWeight: '900', flexShrink: 1 }, personEmail: { color: palette.muted, fontSize: 12, marginTop: 2 }, arrow: { color: palette.orange, fontSize: 26 }, statusLine: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, borderTopWidth: 1, borderTopColor: palette.line, paddingTop: 12 },
  avatar: { width: 48, height: 48, borderRadius: 15, overflow: 'hidden', backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center' }, avatarSmall: { width: 38, height: 38, borderRadius: 12 }, avatarImage: { width: '100%', height: '100%', resizeMode: 'cover' }, avatarText: { color: 'white', fontWeight: '900', fontSize: 15 }, avatarTextSmall: { fontSize: 12 }, pill: { borderRadius: 999, paddingHorizontal: 9, paddingVertical: 5, alignSelf: 'flex-start' }, pillText: { fontSize: 10, fontWeight: '900' }, pillSuccess: { backgroundColor: palette.greenSoft }, pillSuccessText: { color: palette.green }, pillDanger: { backgroundColor: palette.redSoft }, pillDangerText: { color: palette.red }, pillNeutral: { backgroundColor: palette.orangeSoft }, pillNeutralText: { color: '#C2410C' },
  windowCard: { backgroundColor: palette.navy }, smallCaps: { color: palette.orange, fontSize: 10, fontWeight: '900', letterSpacing: 1 }, windowTime: { color: 'white', fontSize: 24, fontWeight: '900', marginVertical: 5 }, classCard: { gap: 10 }, slotCount: { color: palette.muted, fontSize: 12, fontWeight: '800' }, slotRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10, paddingTop: 11, borderTopWidth: 1, borderTopColor: palette.line }, slotTime: { color: palette.ink, fontWeight: '900' }, inlineActions: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 15 },
  laneCard: { flexDirection: 'row', alignItems: 'flex-start', gap: 12 }, laneNumber: { width: 34, height: 34, borderRadius: 11, backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center' }, laneNumberText: { color: 'white', fontWeight: '900' },
  liveCount: { minHeight: 122, backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center' }, liveNumber: { color: 'white', fontSize: 45, fontWeight: '900' }, liveLabel: { color: '#D0D5DD', fontWeight: '800' }, liveDot: { position: 'absolute', top: 15, right: 15, width: 10, height: 10, borderRadius: 5, backgroundColor: '#12B76A' }, liveCar: { flexDirection: 'row', alignItems: 'center', gap: 12 }, warningCard: { borderColor: '#FDA29B', backgroundColor: '#FFFBFA' }, warningText: { color: palette.red, fontSize: 12, fontWeight: '800', marginTop: 5 },
  historySummary: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 }, historyCount: { color: palette.orange, fontSize: 18, fontWeight: '900' }, runCard: { gap: 12 }, runTime: { color: palette.ink, fontSize: 16, fontWeight: '900', marginTop: 3 }, voteLine: { flexDirection: 'row', gap: 14 }, voteUp: { color: palette.green, fontWeight: '900' }, voteDown: { color: palette.red, fontWeight: '900' }, videoButton: { minHeight: 48, borderRadius: 13, paddingHorizontal: 13, backgroundColor: palette.orangeSoft, flexDirection: 'row', alignItems: 'center', gap: 9 }, videoText: { color: '#C2410C', fontWeight: '900' }, videoStatus: { color: palette.muted, fontSize: 12, textTransform: 'capitalize' }, runDrivers: { borderTopWidth: 1, borderTopColor: palette.line }, runDriver: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingTop: 11 }, driverName: { color: palette.ink, fontSize: 14, fontWeight: '900' }, driverCar: { color: palette.muted, fontSize: 12, marginTop: 1 }, driverTimes: { color: palette.muted, fontSize: 10, marginTop: 2 },
  videoModal: { flex: 1, backgroundColor: '#0B1220', paddingTop: 64, paddingHorizontal: 18, paddingBottom: 34, gap: 22 }, videoTitle: { color: 'white', flex: 1, fontSize: 17, fontWeight: '900' }, video: { flex: 1, width: '100%', backgroundColor: 'black', borderRadius: 18 },
  chartCard: { gap: 16 }, barRow: { gap: 7 }, barLabel: { color: palette.ink, fontWeight: '800' }, barValue: { color: palette.orange, fontWeight: '900' }, barTrack: { height: 10, borderRadius: 99, overflow: 'hidden', backgroundColor: '#EAECF0' }, barFill: { height: '100%', borderRadius: 99, backgroundColor: palette.orange },
});
