import { router, useFocusEffect } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useCallback, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import type { DriverRun } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

export default function RunsScreen() {
  const { account, api } = useAuth();
  const [runs, setRuns] = useState<DriverRun[] | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const body = await api<{ runs: DriverRun[] }>('/driver/runs');
      setRuns(body.runs);
    } catch (caught) {
      setRuns([]);
      setError(caught instanceof Error ? caught.message : 'Unable to load your runs.');
    }
  }, [api]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const summary = useMemo(() => {
    if (!runs) return null;
    return {
      total: runs.length,
      tracks: new Set(runs.map(run => run.track.id)).size,
      videos: runs.reduce((total, run) => total + run.videos.filter(video => video.status === 'ready').length, 0),
    };
  }, [runs]);

  if (account?.type !== 'user') return <Screen><Empty title="Driver account required" detail="Run history belongs to driver accounts." /></Screen>;
  if (!runs || !summary) return <Loading />;

  return <Screen>
    <Hero eyebrow="Driver history" title="Your runs" subtitle="Every completed track session, across every event, in one timeline." />
    <View style={styles.stats}>
      <Stat value={summary.total} label="Runs" />
      <Stat value={summary.tracks} label="Tracks" />
      <Stat value={summary.videos} label="Videos" />
    </View>
    <SectionTitle title="Run history" />
    {error ? <Card style={styles.errorCard}><Text style={styles.errorText}>{error}</Text><Pressable onPress={load}><Text style={styles.retry}>Try again</Text></Pressable></Card> : null}
    {runs.length ? <View style={styles.list}>{runs.map(run => <RunRow key={run.id} run={run} />)}</View> : !error ? <Empty title="No completed runs yet" detail="Once you finish a recorded track session, its details and available videos will appear here." /> : null}
  </Screen>;
}

function RunRow({ run }: { run: DriverRun }) {
  const readyVideos = run.videos.filter(video => video.status === 'ready');
  const label = run.event?.name || 'Track session';
  const date = new Date(run.started_at);
  return <Pressable onPress={() => router.push(`/run/${run.id}`)} style={({ pressed }) => pressed && styles.pressed}>
    <Card style={styles.runCard}>
      <View style={styles.dateBlock}>
        <Text style={styles.dateDay}>{date.getDate()}</Text>
        <Text style={styles.dateMonth}>{date.toLocaleString('en-US', { month: 'short' }).toUpperCase()}</Text>
      </View>
      <View style={styles.runCopy}>
        <Text numberOfLines={1} style={styles.runTitle}>{label}</Text>
        <Text numberOfLines={1} style={ui.body}>{run.track.name}{run.car ? ` · ${run.car.label}` : ''}</Text>
        <View style={styles.metaRow}>
          <Text style={styles.time}>{date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}</Text>
          <Text style={styles.dot}>•</Text>
          <Text style={styles.time}>{duration(run.duration_seconds)}</Text>
          {readyVideos.length ? <View style={styles.videoBadge}><SymbolView name={{ ios: 'play.rectangle.fill', android: 'play.rectangle.fill', web: 'play.rectangle.fill' } as any} tintColor={palette.accent} size={12} /><Text style={styles.videoText}>{readyVideos.length} video{readyVideos.length === 1 ? '' : 's'}</Text></View> : null}
        </View>
      </View>
      <Text style={styles.arrow}>›</Text>
    </Card>
  </Pressable>;
}

function Stat({ value, label }: { value: number; label: string }) {
  return <View style={styles.stat}><Text style={styles.statValue}>{value}</Text><Text style={styles.statLabel}>{label}</Text></View>;
}

function duration(seconds?: number | null) {
  if (seconds == null) return 'Time unavailable';
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

const styles = StyleSheet.create({
  stats: { flexDirection: 'row', backgroundColor: palette.surface, borderWidth: 1, borderColor: palette.line, borderRadius: 8, overflow: 'hidden' },
  stat: { flex: 1, alignItems: 'center', paddingVertical: 15, borderRightWidth: StyleSheet.hairlineWidth, borderRightColor: palette.line },
  statValue: { color: palette.ink, fontSize: 22, fontWeight: '900', fontVariant: ['tabular-nums'] },
  statLabel: { color: palette.muted, fontSize: 11, fontWeight: '700', marginTop: 3 },
  list: { gap: 9 },
  runCard: { minHeight: 88, padding: 12, flexDirection: 'row', alignItems: 'center', gap: 12 },
  dateBlock: { width: 50, height: 58, borderRadius: 8, backgroundColor: palette.accentSoft, alignItems: 'center', justifyContent: 'center' },
  dateDay: { color: palette.accent, fontSize: 20, fontWeight: '900', lineHeight: 22 },
  dateMonth: { color: palette.accent, fontSize: 10, fontWeight: '900', letterSpacing: .6 },
  runCopy: { flex: 1, gap: 3 },
  runTitle: { color: palette.ink, fontSize: 16, fontWeight: '900' },
  metaRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6, marginTop: 3 },
  time: { color: palette.muted, fontSize: 11, fontWeight: '700' },
  dot: { color: palette.line, fontSize: 11 },
  videoBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, borderRadius: 999, backgroundColor: palette.accentSoft, paddingHorizontal: 7, paddingVertical: 3 },
  videoText: { color: palette.accent, fontSize: 10, fontWeight: '900' },
  arrow: { color: palette.accent, fontSize: 28 },
  pressed: { opacity: .62 },
  errorCard: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12, backgroundColor: palette.redSoft },
  errorText: { color: palette.red, flex: 1, fontWeight: '700' },
  retry: { color: palette.accent, fontWeight: '900' },
});
