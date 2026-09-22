import * as ImagePicker from 'expo-image-picker';
import { SymbolView } from 'expo-symbols';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { DriverSpaceSwitch } from '@/components/DriverSpaceSwitch';
import { Card, Empty, Field, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate } from '@/lib/format';
import { palette, shadow } from '@/lib/theme';
import type { Car, TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type CommunityUser = {
  id: number;
  username: string;
  name: string;
  initials: string;
  image_url?: string | null;
};

type Connection = {
  id: number;
  status: string;
  requested_by_me: boolean;
  user: CommunityUser;
};

type Comment = {
  id: number;
  body: string;
  created_at: string;
  author: CommunityUser;
};

type CommunityPost = {
  id: number;
  type: string;
  title: string;
  body?: string | null;
  image_url?: string | null;
  created_at: string;
  author: CommunityUser;
  event?: TrackEvent | null;
  car?: Car | null;
  run?: { id: number; started_at: string; ended_at?: string | null; drivers: CommunityUser[] } | null;
  comments: Comment[];
};

type CommunityPayload = {
  me: CommunityUser;
  view: FeedView;
  posts: CommunityPost[];
  connections: Connection[];
  received_requests: Connection[];
  sent_requests: Connection[];
  suggestions: { user: CommunityUser; reason: string }[];
  events: { event: TrackEvent; going_count: number; circle_attendees: CommunityUser[] }[];
};

type FeedView = 'all' | 'mine' | 'track' | 'builds';
type MainView = 'feed' | 'people';

const feedFilters: { value: FeedView; label: string }[] = [
  { value: 'all', label: 'Circle' },
  { value: 'mine', label: 'My feed' },
  { value: 'track', label: 'Track plans' },
  { value: 'builds', label: 'Builds' },
];

function relativeTime(value: string) {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d`;
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function Avatar({ user, size = 44 }: { user: CommunityUser; size?: number }) {
  return <View style={[styles.avatar, { width: size, height: size, borderRadius: size / 2 }]}>
    {user.image_url ? <Image source={{ uri: user.image_url }} style={styles.avatarImage} /> : <Text style={[styles.avatarText, { fontSize: size * .31 }]}>{user.initials}</Text>}
  </View>;
}

function Segmented({ value, onChange }: { value: MainView; onChange: (value: MainView) => void }) {
  return <View style={styles.mainSwitch}>
    {(['feed', 'people'] as MainView[]).map(option => <Pressable key={option} onPress={() => onChange(option)} style={[styles.mainSwitchItem, value === option && styles.mainSwitchItemActive]}>
      <SymbolView name={{ ios: option === 'feed' ? 'rectangle.stack.fill' : 'person.2.fill', android: option === 'feed' ? 'rectangle.stack.fill' : 'person.2.fill', web: option === 'feed' ? 'rectangle.stack.fill' : 'person.2.fill' } as any} tintColor={value === option ? 'white' : '#D0D5DD'} size={17} />
      <Text style={[styles.mainSwitchText, value === option && styles.mainSwitchTextActive]}>{option === 'feed' ? 'Feed' : 'People'}</Text>
    </Pressable>)}
  </View>;
}

export function CommunityExperience({ onShowTrack }: { onShowTrack?: () => void }) {
  const { api } = useAuth();
  const [data, setData] = useState<CommunityPayload | null>(null);
  const [mode, setMode] = useState<MainView>('feed');
  const [view, setView] = useState<FeedView>('all');
  const [peopleQuery, setPeopleQuery] = useState('');
  const [postBody, setPostBody] = useState('');
  const [postImage, setPostImage] = useState<{ uri: string; dataUrl: string } | null>(null);
  const [commentBodies, setCommentBodies] = useState<Record<number, string>>({});
  const [expandedComments, setExpandedComments] = useState<Record<number, boolean>>({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async (selectedView: FeedView, search: string) => {
    setError('');
    try {
      const people = search.trim() ? `&people=${encodeURIComponent(search.trim())}` : '';
      setData(await api<CommunityPayload>(`/driver/community?view=${selectedView}${people}`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load your community.');
    }
  }, [api]);

  useFocusEffect(useCallback(() => { setView('all'); load('all', ''); }, [load]));

  useEffect(() => {
    if (mode !== 'people' || !data) return;
    const timer = setTimeout(() => load(view, peopleQuery), 300);
    return () => clearTimeout(timer);
  }, [peopleQuery, mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const mutate = async (key: string, path: string, init: RequestInit) => {
    setBusy(key);
    setError('');
    try {
      await api(path, init);
      await load(view, peopleQuery);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'That action could not be completed.');
    } finally {
      setBusy('');
    }
  };

  const selectFeed = (next: FeedView) => {
    setView(next);
    setBusy(`feed-${next}`);
    load(next, peopleQuery).finally(() => setBusy(''));
  };

  const choosePhoto = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: true,
      quality: .78,
      base64: true,
      aspect: [4, 3],
    });
    if (result.canceled) return;
    const asset = result.assets[0];
    if (!asset.base64) {
      setError('That photo could not be prepared for upload.');
      return;
    }
    const mime = ['image/jpeg', 'image/png', 'image/webp'].includes(asset.mimeType || '') ? asset.mimeType : 'image/jpeg';
    setPostImage({ uri: asset.uri, dataUrl: `data:${mime};base64,${asset.base64}` });
  };

  const publish = async () => {
    if (!postBody.trim() && !postImage) return;
    setBusy('post');
    setError('');
    try {
      await api('/driver/community/posts', {
        method: 'POST',
        body: JSON.stringify({ body: postBody, image: postImage?.dataUrl || null }),
      });
      setPostBody('');
      setPostImage(null);
      setView('mine');
      await load('mine', peopleQuery);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Your update could not be posted.');
    } finally {
      setBusy('');
    }
  };

  const sendComment = async (postId: number) => {
    const body = (commentBodies[postId] || '').trim();
    if (!body) return;
    await mutate(`comment-${postId}`, `/driver/community/posts/${postId}/comments`, { method: 'POST', body: JSON.stringify({ body }) });
    setCommentBodies(current => ({ ...current, [postId]: '' }));
    setExpandedComments(current => ({ ...current, [postId]: true }));
  };

  const removeConnection = (connection: Connection) => Alert.alert(
    connection.status === 'accepted' ? `Remove @${connection.user.username}?` : 'Remove request?',
    connection.status === 'accepted' ? 'Their posts will no longer appear in your Circle feed.' : 'You can send another request later.',
    [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Remove', style: 'destructive', onPress: () => mutate(`connection-${connection.id}`, `/driver/community/connections/${connection.id}`, { method: 'DELETE' }) },
    ],
  );

  if (!data && !error) return onShowTrack ? <Screen><DriverSpaceSwitch active="social" onChange={space => space === 'track' && onShowTrack()} /><Loading /></Screen> : <Loading />;
  if (!data) return <Screen>{onShowTrack ? <DriverSpaceSwitch active="social" onChange={space => space === 'track' && onShowTrack()} /> : null}<Empty title="Community unavailable" detail={error} /></Screen>;

  return <Screen>
    {onShowTrack ? <DriverSpaceSwitch active="social" onChange={space => space === 'track' && onShowTrack()} /> : null}
    <View style={styles.hero}>
      <View style={styles.heroTop}>
        <View style={{ flex: 1 }}><Text style={styles.eyebrow}>DRIVER COMMUNITY</Text><Text style={styles.heroTitle}>Your circle</Text><Text style={styles.heroSubtitle}>Track life from the people you chose.</Text></View>
        <Avatar user={data.me} size={52} />
      </View>
      <Segmented value={mode} onChange={setMode} />
    </View>

    {error ? <View style={styles.error}><Text style={styles.errorText}>{error}</Text></View> : null}

    {mode === 'feed' ? <FeedViewContent
      data={data}
      view={view}
      busy={busy}
      postBody={postBody}
      postImage={postImage}
      commentBodies={commentBodies}
      expandedComments={expandedComments}
      onSelectFeed={selectFeed}
      onPostBody={setPostBody}
      onChoosePhoto={choosePhoto}
      onRemovePhoto={() => setPostImage(null)}
      onPublish={publish}
      onCommentBody={(postId, body) => setCommentBodies(current => ({ ...current, [postId]: body }))}
      onSendComment={sendComment}
      onToggleComments={postId => setExpandedComments(current => ({ ...current, [postId]: !current[postId] }))}
    /> : <PeopleViewContent
      data={data}
      query={peopleQuery}
      busy={busy}
      onQuery={setPeopleQuery}
      onConnect={userId => mutate(`user-${userId}`, `/driver/community/connections/${userId}`, { method: 'POST' })}
      onAccept={connectionId => mutate(`connection-${connectionId}`, `/driver/community/connections/${connectionId}/accept`, { method: 'POST' })}
      onRemove={removeConnection}
    />}
  </Screen>;
}

export default function CommunityScreen() {
  return <CommunityExperience />;
}

function FeedViewContent({ data, view, busy, postBody, postImage, commentBodies, expandedComments, onSelectFeed, onPostBody, onChoosePhoto, onRemovePhoto, onPublish, onCommentBody, onSendComment, onToggleComments }: {
  data: CommunityPayload;
  view: FeedView;
  busy: string;
  postBody: string;
  postImage: { uri: string; dataUrl: string } | null;
  commentBodies: Record<number, string>;
  expandedComments: Record<number, boolean>;
  onSelectFeed: (view: FeedView) => void;
  onPostBody: (body: string) => void;
  onChoosePhoto: () => void;
  onRemovePhoto: () => void;
  onPublish: () => void;
  onCommentBody: (postId: number, body: string) => void;
  onSendComment: (postId: number) => void;
  onToggleComments: (postId: number) => void;
}) {
  return <>
    <Card style={styles.composer}>
      <View style={styles.composerTop}><Avatar user={data.me} /><Field multiline maxLength={600} value={postBody} onChangeText={onPostBody} placeholder="Share something with your circle…" style={styles.postField} /></View>
      {postImage ? <View><Image source={{ uri: postImage.uri }} style={styles.preview} /><Pressable onPress={onRemovePhoto} style={styles.removePhoto}><Text style={styles.removePhotoText}>Remove photo</Text></Pressable></View> : null}
      <View style={styles.composerActions}>
        <Pressable onPress={onChoosePhoto} style={styles.photoButton}><SymbolView name={{ ios: 'photo.fill', android: 'photo.fill', web: 'photo.fill' } as any} tintColor={palette.orange} size={18} /><Text style={styles.photoButtonText}>Photo</Text></Pressable>
        <Pressable disabled={busy === 'post' || (!postBody.trim() && !postImage)} onPress={onPublish} style={[styles.publishButton, (busy === 'post' || (!postBody.trim() && !postImage)) && styles.disabled]}><Text style={styles.publishText}>{busy === 'post' ? 'Posting…' : 'Post'}</Text></Pressable>
      </View>
    </Card>

    {data.events.length ? <View style={styles.upcomingSection}>
      <SectionTitle title="Coming up" />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.eventRail}>
        {data.events.map(item => <Pressable key={item.event.id} onPress={() => router.push(`/event/${item.event.id}`)} style={({ pressed }) => [styles.eventCard, pressed && styles.pressed]}>
          <Text style={styles.eventDate}>{eventDate(item.event.date)}</Text><Text numberOfLines={2} style={styles.eventName}>{item.event.name}</Text><Text numberOfLines={1} style={styles.eventTrack}>{item.event.track.name}</Text>
          <View style={styles.goingRow}><View style={styles.avatarStack}>{item.circle_attendees.slice(0, 3).map((user, index) => <View key={user.id} style={{ marginLeft: index ? -8 : 0, zIndex: 3 - index }}><Avatar user={user} size={28} /></View>)}</View><Text style={styles.goingText}>{item.going_count} going</Text></View>
        </Pressable>)}
      </ScrollView>
    </View> : null}

    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filters}>
      {feedFilters.map(filter => <Pressable key={filter.value} onPress={() => onSelectFeed(filter.value)} style={[styles.filter, view === filter.value && styles.filterActive]}><Text style={[styles.filterText, view === filter.value && styles.filterTextActive]}>{busy === `feed-${filter.value}` ? 'Loading…' : filter.label}</Text></Pressable>)}
    </ScrollView>

    <SectionTitle title={view === 'all' ? 'From your circle' : feedFilters.find(filter => filter.value === view)?.label || 'Updates'} />
    {data.posts.length ? data.posts.map(post => <PostCard key={post.id} post={post} busy={busy} commentBody={commentBodies[post.id] || ''} expanded={!!expandedComments[post.id]} onCommentBody={body => onCommentBody(post.id, body)} onSendComment={() => onSendComment(post.id)} onToggleComments={() => onToggleComments(post.id)} />) : <Empty title={view === 'all' ? 'Your circle is quiet' : 'Nothing here yet'} detail={view === 'all' ? 'Connect with drivers in People. Their posts will appear here—your own posts stay in My feed.' : 'Updates for this view will appear here.'} />}
  </>;
}

function PostCard({ post, busy, commentBody, expanded, onCommentBody, onSendComment, onToggleComments }: { post: CommunityPost; busy: string; commentBody: string; expanded: boolean; onCommentBody: (body: string) => void; onSendComment: () => void; onToggleComments: () => void }) {
  const comments = expanded ? post.comments : post.comments.slice(-2);
  return <Card style={styles.post}>
    <View style={styles.postHead}><Avatar user={post.author} /><View style={{ flex: 1 }}><Text style={styles.author}>@{post.author.username}</Text><Text style={styles.meta}>{post.title} · {relativeTime(post.created_at)}</Text></View></View>
    {post.body ? <Text style={styles.postBody}>{post.body}</Text> : null}
    {post.image_url ? <Image source={{ uri: post.image_url }} style={styles.postImage} /> : null}
    {post.event ? <Pressable onPress={() => router.push(`/event/${post.event!.id}`)} style={styles.attachment}><View style={styles.attachmentIcon}><SymbolView name={{ ios: 'flag.checkered', android: 'flag.checkered', web: 'flag.checkered' } as any} tintColor={palette.orange} size={19} /></View><View style={{ flex: 1 }}><Text style={styles.attachmentLabel}>{post.run ? 'SHARED RUN' : 'EVENT'}</Text><Text style={styles.attachmentTitle}>{post.event.name}</Text><Text style={styles.attachmentDetail}>{eventDate(post.event.date)} · {post.event.track.name}</Text></View><Text style={styles.arrow}>›</Text></Pressable> : null}
    {post.run?.drivers.length ? <View style={styles.runDrivers}><Text style={styles.runLabel}>Drivers in this run</Text><Text style={styles.runNames} numberOfLines={2}>{post.run.drivers.map(driver => driver.name).join(' · ')}</Text></View> : null}
    {post.car ? <View style={styles.attachment}><View style={[styles.attachmentIcon, styles.carIcon]}><SymbolView name={{ ios: 'car.fill', android: 'car.fill', web: 'car.fill' } as any} tintColor={palette.navy} size={19} /></View><View style={{ flex: 1 }}><Text style={styles.attachmentLabel}>GARAGE</Text><Text style={styles.attachmentTitle}>{post.car.label}</Text>{post.car.color ? <Text style={styles.attachmentDetail}>{post.car.color}</Text> : null}</View></View> : null}
    <View style={styles.commentDivider} />
    {post.comments.length > 2 ? <Pressable onPress={onToggleComments}><Text style={styles.commentToggle}>{expanded ? 'Show recent comments' : `View all ${post.comments.length} comments`}</Text></Pressable> : null}
    {comments.map(comment => <View key={comment.id} style={styles.comment}><Avatar user={comment.author} size={30} /><View style={styles.commentBubble}><Text style={styles.commentAuthor}>@{comment.author.username} <Text style={styles.commentTime}>{relativeTime(comment.created_at)}</Text></Text><Text style={styles.commentBody}>{comment.body}</Text></View></View>)}
    <View style={styles.commentForm}><Field value={commentBody} maxLength={400} onChangeText={onCommentBody} placeholder="Write a comment…" style={styles.commentField} onSubmitEditing={onSendComment} /><Pressable disabled={!commentBody.trim() || busy === `comment-${post.id}`} onPress={onSendComment} style={[styles.sendButton, (!commentBody.trim() || busy === `comment-${post.id}`) && styles.disabled]}><SymbolView name={{ ios: 'arrow.up', android: 'arrow.up', web: 'arrow.up' } as any} tintColor="white" size={16} /></Pressable></View>
  </Card>;
}

function PeopleViewContent({ data, query, busy, onQuery, onConnect, onAccept, onRemove }: { data: CommunityPayload; query: string; busy: string; onQuery: (query: string) => void; onConnect: (userId: number) => void; onAccept: (connectionId: number) => void; onRemove: (connection: Connection) => void }) {
  const sections = useMemo(() => [
    { title: query.trim() ? 'Search results' : 'People you may know', rows: data.suggestions },
  ], [data.suggestions, query]);
  return <>
    <View style={styles.peopleIntro}><Text style={styles.peopleTitle}>Find your people</Text><Text style={ui.body}>Search by username or name. Only accepted connections appear in your Circle feed.</Text></View>
    <Field value={query} onChangeText={onQuery} autoCapitalize="none" autoCorrect={false} placeholder="Search drivers as you type" />

    {data.received_requests.length ? <View style={styles.peopleSection}><SectionTitle title={`Requests (${data.received_requests.length})`} />{data.received_requests.map(connection => <PersonRow key={connection.id} user={connection.user} detail="Wants to connect" primary="Accept" secondary="Decline" busy={busy === `connection-${connection.id}`} onPrimary={() => onAccept(connection.id)} onSecondary={() => onRemove(connection)} />)}</View> : null}

    {sections.map(section => <View key={section.title} style={styles.peopleSection}><SectionTitle title={section.title} />{section.rows.length ? section.rows.map(item => <PersonRow key={item.user.id} user={item.user} detail={item.reason} primary="Connect" busy={busy === `user-${item.user.id}`} onPrimary={() => onConnect(item.user.id)} />) : <Empty title={query.trim() ? 'No drivers found' : 'No suggestions yet'} detail={query.trim() ? 'Try another username or name.' : 'Shared events and followed tracks will help find familiar drivers.'} />}</View>)}

    <View style={styles.peopleSection}><SectionTitle title={`Your circle (${data.connections.length})`} />{data.connections.length ? data.connections.map(connection => <PersonRow key={connection.id} user={connection.user} detail="Connected" secondary="Remove" busy={busy === `connection-${connection.id}`} onSecondary={() => onRemove(connection)} />) : <Empty title="No connections yet" detail="Find a driver above and send your first request." />}</View>

    {data.sent_requests.length ? <View style={styles.peopleSection}><SectionTitle title="Pending" />{data.sent_requests.map(connection => <PersonRow key={connection.id} user={connection.user} detail="Request sent" secondary="Cancel" busy={busy === `connection-${connection.id}`} onSecondary={() => onRemove(connection)} />)}</View> : null}
  </>;
}

function PersonRow({ user, detail, primary, secondary, busy, onPrimary, onSecondary }: { user: CommunityUser; detail: string; primary?: string; secondary?: string; busy: boolean; onPrimary?: () => void; onSecondary?: () => void }) {
  return <Card style={styles.personRow}><Avatar user={user} /><View style={{ flex: 1 }}><Text style={styles.personName}>{user.name}</Text><Text style={styles.personHandle}>@{user.username} · {detail}</Text></View><View style={styles.personActions}>{primary ? <Pressable disabled={busy} onPress={onPrimary} style={[styles.smallPrimary, busy && styles.disabled]}><Text style={styles.smallPrimaryText}>{busy ? '…' : primary}</Text></Pressable> : null}{secondary ? <Pressable disabled={busy} onPress={onSecondary}><Text style={styles.secondaryAction}>{secondary}</Text></Pressable> : null}</View></Card>;
}

const styles = StyleSheet.create({
  hero: { backgroundColor: palette.navy, borderRadius: 24, padding: 18, gap: 18, ...shadow },
  heroTop: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  eyebrow: { color: '#FDBA74', fontSize: 11, fontWeight: '900', letterSpacing: 1.2, marginBottom: 5 },
  heroTitle: { color: 'white', fontSize: 27, lineHeight: 30, fontWeight: '900' },
  heroSubtitle: { color: '#D0D5DD', fontSize: 13, marginTop: 4 },
  mainSwitch: { flexDirection: 'row', borderRadius: 13, padding: 4, backgroundColor: 'rgba(255,255,255,.09)' },
  mainSwitchItem: { flex: 1, minHeight: 39, borderRadius: 10, flexDirection: 'row', gap: 7, alignItems: 'center', justifyContent: 'center' },
  mainSwitchItemActive: { backgroundColor: palette.orange }, mainSwitchText: { color: '#D0D5DD', fontWeight: '800' }, mainSwitchTextActive: { color: 'white' },
  error: { padding: 13, borderRadius: 13, backgroundColor: palette.redSoft }, errorText: { color: palette.red, fontWeight: '800', lineHeight: 19 },
  composer: { gap: 12 }, composerTop: { flexDirection: 'row', alignItems: 'flex-start', gap: 11 }, postField: { flex: 1, height: 86, paddingTop: 13, textAlignVertical: 'top' },
  composerActions: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, photoButton: { flexDirection: 'row', gap: 7, alignItems: 'center', paddingVertical: 9, paddingHorizontal: 5 }, photoButtonText: { color: palette.orange, fontWeight: '900' }, publishButton: { backgroundColor: palette.orange, minWidth: 82, minHeight: 40, borderRadius: 12, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 15 }, publishText: { color: 'white', fontWeight: '900' },
  preview: { width: '100%', height: 210, borderRadius: 14, backgroundColor: palette.canvas }, removePhoto: { position: 'absolute', top: 10, right: 10, backgroundColor: 'rgba(16,24,40,.82)', borderRadius: 999, paddingHorizontal: 11, paddingVertical: 7 }, removePhotoText: { color: 'white', fontWeight: '800', fontSize: 11 },
  upcomingSection: { gap: 10 }, eventRail: { gap: 10, paddingRight: 2 }, eventCard: { width: 215, minHeight: 145, borderRadius: 18, padding: 15, backgroundColor: 'white', borderWidth: 1, borderColor: palette.line, ...shadow }, eventDate: { color: palette.orange, fontSize: 11, fontWeight: '900', textTransform: 'uppercase' }, eventName: { color: palette.ink, fontSize: 17, lineHeight: 21, fontWeight: '900', marginTop: 7 }, eventTrack: { color: palette.muted, fontSize: 12, marginTop: 4 }, goingRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 'auto', paddingTop: 10 }, avatarStack: { flexDirection: 'row' }, goingText: { color: palette.muted, fontSize: 11, fontWeight: '700' },
  filters: { gap: 8 }, filter: { borderWidth: 1, borderColor: palette.line, backgroundColor: 'white', borderRadius: 999, paddingHorizontal: 15, paddingVertical: 9 }, filterActive: { borderColor: palette.navy, backgroundColor: palette.navy }, filterText: { color: palette.muted, fontSize: 12, fontWeight: '800' }, filterTextActive: { color: 'white' },
  post: { gap: 12 }, postHead: { flexDirection: 'row', alignItems: 'center', gap: 11 }, author: { color: palette.ink, fontWeight: '900', fontSize: 15 }, meta: { color: palette.muted, fontSize: 11, marginTop: 3 }, postBody: { color: palette.ink, fontSize: 15, lineHeight: 22 }, postImage: { width: '100%', height: 255, borderRadius: 15, backgroundColor: palette.canvas },
  attachment: { borderWidth: 1, borderColor: palette.line, backgroundColor: '#FCFCFD', borderRadius: 14, padding: 12, flexDirection: 'row', alignItems: 'center', gap: 11 }, attachmentIcon: { width: 40, height: 40, borderRadius: 12, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' }, carIcon: { backgroundColor: '#E9EEF7' }, attachmentLabel: { color: palette.orange, fontSize: 9, letterSpacing: 1, fontWeight: '900' }, attachmentTitle: { color: palette.ink, fontSize: 14, fontWeight: '900', marginTop: 2 }, attachmentDetail: { color: palette.muted, fontSize: 11, marginTop: 2 }, arrow: { color: palette.orange, fontSize: 25 },
  runDrivers: { backgroundColor: palette.orangeSoft, borderRadius: 12, padding: 11 }, runLabel: { color: '#C2410C', fontSize: 10, fontWeight: '900', textTransform: 'uppercase' }, runNames: { color: palette.ink, fontSize: 12, lineHeight: 18, fontWeight: '700', marginTop: 3 },
  commentDivider: { height: 1, backgroundColor: palette.line }, commentToggle: { color: palette.orange, fontSize: 12, fontWeight: '800' }, comment: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 }, commentBubble: { flex: 1, backgroundColor: palette.canvas, borderRadius: 13, paddingHorizontal: 11, paddingVertical: 8 }, commentAuthor: { color: palette.ink, fontSize: 11, fontWeight: '900' }, commentTime: { color: palette.muted, fontWeight: '600' }, commentBody: { color: palette.ink, fontSize: 13, lineHeight: 18, marginTop: 2 }, commentForm: { flexDirection: 'row', gap: 8, alignItems: 'center' }, commentField: { flex: 1, height: 44, fontSize: 14 }, sendButton: { width: 42, height: 42, borderRadius: 13, backgroundColor: palette.orange, alignItems: 'center', justifyContent: 'center' },
  peopleIntro: { gap: 4 }, peopleTitle: { color: palette.ink, fontSize: 22, fontWeight: '900' }, peopleSection: { gap: 9 }, personRow: { padding: 12, flexDirection: 'row', alignItems: 'center', gap: 11 }, personName: { color: palette.ink, fontWeight: '900', fontSize: 14 }, personHandle: { color: palette.muted, fontSize: 11, marginTop: 3 }, personActions: { alignItems: 'flex-end', gap: 5 }, smallPrimary: { minWidth: 72, minHeight: 34, borderRadius: 10, backgroundColor: palette.orange, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 10 }, smallPrimaryText: { color: 'white', fontWeight: '900', fontSize: 12 }, secondaryAction: { color: palette.muted, fontSize: 11, fontWeight: '800', paddingHorizontal: 5, paddingVertical: 3 },
  avatar: { backgroundColor: palette.orangeSoft, overflow: 'hidden', alignItems: 'center', justifyContent: 'center', borderWidth: 2, borderColor: 'white' }, avatarImage: { width: '100%', height: '100%' }, avatarText: { color: '#C2410C', fontWeight: '900' }, pressed: { opacity: .65 }, disabled: { opacity: .45 },
});
