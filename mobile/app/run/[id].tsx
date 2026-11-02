import { useFocusEffect, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useCallback, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import type { DriverRun, RunVideo } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

export default function RunDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { account, api } = useAuth();
  const [run, setRun] = useState<DriverRun | null>(null);
  const [failed, setFailed] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setFailed(false);
    try {
      const body = await api<{ run: DriverRun }>(`/driver/runs/${id}`);
      setRun(body.run);
    } catch {
      setFailed(true);
    }
  }, [api, id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const share = async () => {
    if (!run || run.shared) return;
    setSharing(true);
    setNotice('');
    try {
      const body = await api<{ message: string; shared: boolean }>(`/driver/runs/${run.id}/share`, { method: 'POST', body: '{}' });
      setRun({ ...run, shared: body.shared });
      setNotice(body.message);
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : 'Unable to share this run.');
    } finally {
      setSharing(false);
    }
  };

  if (account?.type !== 'user') return <Screen><Empty title="Driver account required" detail="Only drivers can view a personal run history." /></Screen>;
  if (!run && !failed) return <Loading />;
  if (!run) return <Screen><Empty title="Run unavailable" detail="This run was not found in your driver history." /><Button title="Try again" onPress={load} /></Screen>;

  const readyVideos = run.videos.filter(video => video.status === 'ready' && video.url);
  const pendingVideos = run.videos.filter(video => video.status !== 'ready' || !video.url);
  const start = new Date(run.started_at);

  return <Screen>
    <View style={styles.header}>
      <View style={styles.headerIcon}><SymbolView name={{ ios: 'flag.checkered', android: 'flag.checkered', web: 'flag.checkered' } as any} tintColor={palette.accent} size={27} /></View>
      <View style={styles.headerCopy}><Text style={styles.eyebrow}>COMPLETED RUN</Text><Text style={styles.title}>{run.event?.name || 'Track session'}</Text><Text style={styles.subtitle}>{run.track.name} · {start.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</Text></View>
    </View>

    <Card style={styles.summary}>
      <Detail label="Started" value={start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })} />
      <Detail label="Run time" value={duration(run.duration_seconds)} divided />
      <Detail label="Vehicle" value={run.car?.label || 'Not recorded'} divided />
      <Detail label="Location" value={run.track.location || run.track.name} divided />
    </Card>

    <SectionTitle title={readyVideos.length === 1 ? 'Run video' : 'Run videos'} />
    {readyVideos.length ? readyVideos.map(video => <RunVideoPlayer key={video.id} video={video} />) : <Empty title="No video available" detail={pendingVideos.length ? 'The recording is still processing or is not currently available.' : 'No camera recording was attached to this run.'} />}

    <SectionTitle title={`Drivers in this run · ${run.participants.length}`} />
    <Card style={styles.participants}>
      {run.participants.map((participant, index) => <View key={`${participant.driver.id}-${participant.car.id}`} style={[styles.participant, index > 0 && styles.divider]}>
        <View style={styles.avatar}><Text style={styles.avatarText}>{participant.driver.initials}</Text></View>
        <View style={styles.participantCopy}><Text style={styles.participantName}>{participant.driver.name}</Text><Text style={ui.body}>{participant.car.label}</Text></View>
        {participant.driver.id === account.id ? <Text style={styles.you}>YOU</Text> : null}
      </View>)}
    </Card>

    {notice ? <View style={[styles.notice, run.shared ? styles.successNotice : styles.errorNotice]}><Text style={[styles.noticeText, { color: run.shared ? palette.green : palette.red }]}>{notice}</Text></View> : null}
    <Button title={run.shared ? 'Shared to Social' : sharing ? 'Sharing…' : 'Share to Social'} disabled={run.shared || sharing} onPress={share} />
    <Text style={styles.shareNote}>{run.shared ? 'This run is already visible on your feed.' : 'Share the event, track, drivers, and run time with your connections.'}</Text>
  </Screen>;
}

function RunVideoPlayer({ video }: { video: RunVideo & { url?: string | null } }) {
  const player = useVideoPlayer(video.url || '', instance => { instance.loop = false; });
  return <Card style={styles.videoCard}>
    <VideoView player={player} nativeControls contentFit="contain" fullscreenOptions={{ enable: true }} style={styles.video} />
    <View style={styles.videoFooter}><View style={styles.videoIcon}><SymbolView name={{ ios: 'video.fill', android: 'video.fill', web: 'video.fill' } as any} tintColor={palette.accent} size={16} /></View><Text style={styles.videoName}>{video.name}</Text><Text style={styles.ready}>READY</Text></View>
  </Card>;
}

function Detail({ label, value, divided = false }: { label: string; value: string; divided?: boolean }) {
  return <View style={[styles.detail, divided && styles.divider]}><Text style={styles.detailLabel}>{label}</Text><Text numberOfLines={2} style={styles.detailValue}>{value}</Text></View>;
}

function duration(seconds?: number | null) {
  if (seconds == null) return 'Not recorded';
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes ? `${minutes} min ${remainder} sec` : `${remainder} sec`;
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', gap: 14, padding: 17, borderRadius: 8, borderWidth: 1, borderColor: palette.line, backgroundColor: palette.navy },
  headerIcon: { width: 52, height: 52, borderRadius: 8, backgroundColor: palette.accentSoft, alignItems: 'center', justifyContent: 'center' },
  headerCopy: { flex: 1, gap: 3 },
  eyebrow: { color: palette.accent, fontSize: 10, fontWeight: '900', letterSpacing: 1.2 },
  title: { color: palette.ink, fontSize: 21, fontWeight: '900' },
  subtitle: { color: palette.muted, fontSize: 13, lineHeight: 18 },
  summary: { paddingVertical: 2 },
  detail: { minHeight: 58, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 18, paddingVertical: 12 },
  detailLabel: { color: palette.muted, fontSize: 13, fontWeight: '700' },
  detailValue: { color: palette.ink, flex: 1, textAlign: 'right', fontSize: 14, fontWeight: '900' },
  divider: { borderTopWidth: 1, borderTopColor: palette.line },
  videoCard: { padding: 0, overflow: 'hidden' },
  video: { width: '100%', aspectRatio: 16 / 9, backgroundColor: '#050A12' },
  videoFooter: { minHeight: 52, flexDirection: 'row', alignItems: 'center', gap: 9, paddingHorizontal: 13 },
  videoIcon: { width: 30, height: 30, borderRadius: 8, backgroundColor: palette.accentSoft, alignItems: 'center', justifyContent: 'center' },
  videoName: { color: palette.ink, flex: 1, fontWeight: '800' },
  ready: { color: palette.green, fontSize: 10, fontWeight: '900', letterSpacing: .7 },
  participants: { paddingVertical: 2 },
  participant: { minHeight: 66, flexDirection: 'row', alignItems: 'center', gap: 11, paddingVertical: 10 },
  avatar: { width: 42, height: 42, borderRadius: 21, backgroundColor: palette.accentSoft, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: palette.accent, fontSize: 13, fontWeight: '900' },
  participantCopy: { flex: 1 },
  participantName: { color: palette.ink, fontSize: 15, fontWeight: '900' },
  you: { color: palette.accent, fontSize: 10, fontWeight: '900', letterSpacing: .7 },
  notice: { padding: 13, borderRadius: 8 },
  successNotice: { backgroundColor: palette.greenSoft },
  errorNotice: { backgroundColor: palette.redSoft },
  noticeText: { textAlign: 'center', fontWeight: '800' },
  shareNote: { color: palette.muted, textAlign: 'center', fontSize: 11, lineHeight: 17, paddingHorizontal: 12 },
});
