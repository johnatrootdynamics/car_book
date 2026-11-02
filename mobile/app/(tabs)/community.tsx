import * as ImagePicker from 'expo-image-picker';
import { SymbolView } from 'expo-symbols';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Image, Linking, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

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
  reaction_count: number;
  reacted_by_me: boolean;
  share_count: number;
  is_owner: boolean;
  shared_post?: CommunityPost | null;
  share_id?: number | null;
  interaction_post_id: number;
};

type ActivityItem = {
  id: string;
  type: 'comment' | 'reaction' | 'share';
  created_at: string;
  actor: CommunityUser;
  post_id: number;
  detail?: string | null;
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
  activity: ActivityItem[];
  blocked_users: CommunityUser[];
};

type FeedView = 'all' | 'mine' | 'track' | 'builds';
type MainView = 'feed' | 'events' | 'people' | 'activity';

const feedFilters: { value: FeedView; label: string; detail: string }[] = [
  { value: 'all', label: 'Circle', detail: 'Posts from your connections' },
  { value: 'mine', label: 'My posts', detail: 'Updates you have shared' },
  { value: 'track', label: 'Track plans', detail: 'Upcoming plans and events' },
  { value: 'builds', label: 'Builds', detail: 'Cars and garage updates' },
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

export function CommunityExperience({ onShowTrack }: { onShowTrack?: () => void }) {
  const { api } = useAuth();
  const [data, setData] = useState<CommunityPayload | null>(null);
  const [mode, setMode] = useState<MainView>('feed');
  const [view, setView] = useState<FeedView>('all');
  const [peopleQuery, setPeopleQuery] = useState('');
  const [postBody, setPostBody] = useState('');
  const [postImage, setPostImage] = useState<{ uri: string; dataUrl: string } | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
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

  useFocusEffect(useCallback(() => {
    setView('all');
    load('all', '');
  }, [load]));

  useEffect(() => {
    if (mode !== 'people') return;
    const timer = setTimeout(() => load(view, peopleQuery), 300);
    return () => clearTimeout(timer);
  }, [peopleQuery, mode, view, load]);

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
    setMode('feed');
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
      setComposerOpen(false);
      setView('mine');
      setMode('feed');
      await load('mine', peopleQuery);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Your update could not be posted.');
    } finally {
      setBusy('');
    }
  };

  const sendComment = async (cardId: number, postId: number) => {
    const body = (commentBodies[cardId] || '').trim();
    if (!body) return;
    await mutate(`comment-${cardId}`, `/driver/community/posts/${postId}/comments`, { method: 'POST', body: JSON.stringify({ body }) });
    setCommentBodies(current => ({ ...current, [cardId]: '' }));
    setExpandedComments(current => ({ ...current, [cardId]: true }));
  };

  const sharePost = (post: CommunityPost) => Alert.alert(
    'Share to your feed?',
    `Your connections will see ${post.author.name}’s post in your feed.`,
    [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Share', onPress: () => mutate(`share-${post.id}`, `/driver/community/posts/${post.interaction_post_id}/share`, { method: 'POST', body: '{}' }) },
    ],
  );

  const deletePost = (post: CommunityPost) => Alert.alert(
    'Delete this post?',
    'This also removes its reactions and comments. This cannot be undone.',
    [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: () => mutate(`delete-${post.id}`, post.share_id ? `/driver/community/shares/${post.share_id}` : `/driver/community/posts/${post.id}`, { method: 'DELETE' }) },
    ],
  );

  const removeConnection = (connection: Connection) => Alert.alert(
    connection.status === 'accepted' ? `Remove @${connection.user.username}?` : 'Remove request?',
    connection.status === 'accepted' ? 'Their posts will no longer appear in your Circle feed.' : 'You can send another request later.',
    [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Remove', style: 'destructive', onPress: () => mutate(`connection-${connection.id}`, `/driver/community/connections/${connection.id}`, { method: 'DELETE' }) },
    ],
  );

  const report = (kind: 'posts' | 'shares' | 'comments' | 'users', id: number, label: string) => {
    const submit = async (reason: string) => {
      setBusy(`report-${kind}-${id}`);
      setError('');
      try {
        const result = await api<{ message: string }>(`/driver/community/${kind}/${id}/report`, {
          method: 'POST',
          body: JSON.stringify({ reason }),
        });
        Alert.alert('Report received', result.message);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : 'The report could not be sent.');
      } finally {
        setBusy('');
      }
    };
    Alert.alert(`Report ${label}?`, 'Reports are private and reviewed by the Track Ops safety team.', [
      { text: 'Spam or misleading', onPress: () => submit('spam') },
      { text: 'Harassment or unsafe', onPress: () => submit('harassment') },
      { text: 'Hate, violence, or sexual content', onPress: () => submit('violence') },
      { text: 'Cancel', style: 'cancel' },
    ]);
  };

  const blockUser = (user: CommunityUser) => Alert.alert(
    `Block @${user.username}?`,
    'You will be disconnected and neither of you will see the other in Community. You can unblock them later.',
    [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Block', style: 'destructive', onPress: () => mutate(`block-${user.id}`, `/driver/community/users/${user.id}/block`, { method: 'POST', body: '{}' }) },
    ],
  );

  const postOptions = (post: CommunityPost) => {
    if (post.is_owner) {
      deletePost(post);
      return;
    }
    Alert.alert('Post options', `Manage content from @${post.author.username}.`, [
      { text: 'Report post', onPress: () => report(post.share_id ? 'shares' : 'posts', post.share_id || post.interaction_post_id, 'post') },
      { text: `Block @${post.author.username}`, style: 'destructive', onPress: () => blockUser(post.author) },
      { text: 'Cancel', style: 'cancel' },
    ]);
  };

  const commentOptions = (comment: Comment) => Alert.alert(
    'Comment options',
    `Manage this comment from @${comment.author.username}.`,
    [
      { text: 'Report comment', onPress: () => report('comments', comment.id, 'comment') },
      { text: `Block @${comment.author.username}`, style: 'destructive', onPress: () => blockUser(comment.author) },
      { text: 'Cancel', style: 'cancel' },
    ],
  );

  if (!data && !error) return <Loading />;
  if (!data) return <Screen><Empty title="Community unavailable" detail={error} /></Screen>;

  const requestCount = data.received_requests.length;
  return <Screen>
    <SocialHeader mode={mode} requestCount={requestCount} onShowTrack={onShowTrack} onActivity={() => setMode('activity')} onCompose={() => setComposerOpen(true)} />
    <SocialShortcuts
      me={data.me}
      mode={mode}
      view={view}
      requestCount={requestCount}
      onMode={setMode}
      onFeed={selectFeed}
    />

    {error ? <View style={styles.error}><Text style={styles.errorText}>{error}</Text></View> : null}

    {mode === 'feed' ? <FeedViewContent
      data={data}
      view={view}
      busy={busy}
      commentBodies={commentBodies}
      expandedComments={expandedComments}
      onReact={post => mutate(`react-${post.id}`, `/driver/community/posts/${post.interaction_post_id}/react`, { method: 'POST' })}
      onShare={sharePost}
      onOptions={postOptions}
      onCommentOptions={commentOptions}
      onCommentBody={(postId, body) => setCommentBodies(current => ({ ...current, [postId]: body }))}
      onSendComment={sendComment}
      onToggleComments={postId => setExpandedComments(current => ({ ...current, [postId]: !current[postId] }))}
    /> : null}

    {mode === 'events' ? <EventsViewContent data={data} /> : null}

    {mode === 'people' ? <PeopleViewContent
      data={data}
      query={peopleQuery}
      busy={busy}
      onQuery={setPeopleQuery}
      onConnect={userId => mutate(`user-${userId}`, `/driver/community/connections/${userId}`, { method: 'POST' })}
      onAccept={connectionId => mutate(`connection-${connectionId}`, `/driver/community/connections/${connectionId}/accept`, { method: 'POST' })}
      onRemove={removeConnection}
      onBlock={blockUser}
      onUnblock={user => mutate(`unblock-${user.id}`, `/driver/community/users/${user.id}/block`, { method: 'DELETE' })}
    /> : null}

    {mode === 'activity' ? <ActivityViewContent
      data={data}
      busy={busy}
      onAccept={connectionId => mutate(`connection-${connectionId}`, `/driver/community/connections/${connectionId}/accept`, { method: 'POST' })}
      onRemove={removeConnection}
      onOpenPost={() => selectFeed('mine')}
    /> : null}

    <ComposerModal
      visible={composerOpen}
      me={data.me}
      body={postBody}
      image={postImage}
      busy={busy === 'post'}
      onBody={setPostBody}
      onPhoto={choosePhoto}
      onRemovePhoto={() => setPostImage(null)}
      onClose={() => setComposerOpen(false)}
      onPublish={publish}
    />
  </Screen>;
}

function SocialHeader({ mode, requestCount, onShowTrack, onActivity, onCompose }: { mode: MainView; requestCount: number; onShowTrack?: () => void; onActivity: () => void; onCompose: () => void }) {
  return <View style={styles.instagramHeader}>
    <View style={styles.instagramTitleRow}>
      {onShowTrack ? <Pressable accessibilityRole="button" accessibilityLabel="Back to Track" onPress={onShowTrack} style={({ pressed }) => [styles.backToTrack, pressed && styles.pressed]}><SymbolView name={{ ios: 'chevron.left', android: 'chevron.left', web: 'chevron.left' } as any} tintColor={palette.accent} size={15} /><Text style={styles.backToTrackText}>Track</Text></Pressable> : null}
      <Text style={styles.instagramTitle}>Social</Text>
    </View>
    <View style={styles.instagramActions}>
      <Pressable accessibilityRole="button" accessibilityLabel="Create post" onPress={onCompose} style={({ pressed }) => [styles.instagramAction, pressed && styles.pressed]}><SymbolView name={{ ios: 'plus.app', android: 'add_box', web: 'add_box' } as any} tintColor={palette.ink} size={25} /></Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel="Activity" onPress={onActivity} style={({ pressed }) => [styles.instagramAction, mode === 'activity' && styles.instagramActionActive, pressed && styles.pressed]}>
        <SymbolView name={{ ios: mode === 'activity' ? 'heart.fill' : 'heart', android: mode === 'activity' ? 'favorite' : 'favorite_border', web: mode === 'activity' ? 'favorite' : 'favorite_border' } as any} tintColor={mode === 'activity' ? palette.accent : palette.ink} size={25} />
        {requestCount ? <View style={styles.headerBadge}><Text style={styles.headerBadgeText}>{requestCount > 9 ? '9+' : requestCount}</Text></View> : null}
      </Pressable>
    </View>
  </View>;
}

function SocialShortcuts({ me, mode, view, requestCount, onMode, onFeed }: { me: CommunityUser; mode: MainView; view: FeedView; requestCount: number; onMode: (mode: MainView) => void; onFeed: (view: FeedView) => void }) {
  const shortcuts: { key: string; label: string; symbol?: string; active: boolean; badge?: number; avatar?: boolean; onPress: () => void }[] = [
    { key: 'circle', label: 'Circle', symbol: 'house.fill', active: mode === 'feed' && view === 'all', onPress: () => onFeed('all') },
    { key: 'people', label: 'People', symbol: 'person.2.fill', active: mode === 'people', badge: requestCount, onPress: () => onMode('people') },
    { key: 'events', label: 'Events', symbol: 'calendar', active: mode === 'events', onPress: () => onMode('events') },
    { key: 'mine', label: 'My posts', active: mode === 'feed' && view === 'mine', avatar: true, onPress: () => onFeed('mine') },
    { key: 'track', label: 'Plans', symbol: 'flag.checkered', active: mode === 'feed' && view === 'track', onPress: () => onFeed('track') },
    { key: 'builds', label: 'Builds', symbol: 'car.fill', active: mode === 'feed' && view === 'builds', onPress: () => onFeed('builds') },
  ];
  return <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.shortcutScroller} contentContainerStyle={styles.shortcuts}>
    {shortcuts.map(shortcut => <Pressable key={shortcut.key} accessibilityRole="button" accessibilityLabel={shortcut.label} accessibilityState={{ selected: shortcut.active }} onPress={shortcut.onPress} style={({ pressed }) => [styles.shortcut, pressed && styles.pressed]}>
      <View style={[styles.shortcutRing, shortcut.active && styles.shortcutRingActive]}>
        {shortcut.avatar ? <Avatar user={me} size={52} /> : <View style={[styles.shortcutIcon, shortcut.active && styles.shortcutIconActive]}><SymbolView name={{ ios: shortcut.symbol!, android: shortcut.symbol!, web: shortcut.symbol! } as any} tintColor={shortcut.active ? 'white' : palette.ink} size={22} /></View>}
        {shortcut.badge ? <View style={styles.shortcutBadge}><Text style={styles.shortcutBadgeText}>{shortcut.badge > 9 ? '9+' : shortcut.badge}</Text></View> : null}
      </View>
      <Text numberOfLines={1} style={[styles.shortcutLabel, shortcut.active && styles.shortcutLabelActive]}>{shortcut.label}</Text>
    </Pressable>)}
  </ScrollView>;
}

function FeedViewContent({ data, view, busy, commentBodies, expandedComments, onReact, onShare, onOptions, onCommentOptions, onCommentBody, onSendComment, onToggleComments }: {
  data: CommunityPayload;
  view: FeedView;
  busy: string;
  commentBodies: Record<number, string>;
  expandedComments: Record<number, boolean>;
  onReact: (post: CommunityPost) => void;
  onShare: (post: CommunityPost) => void;
  onOptions: (post: CommunityPost) => void;
  onCommentOptions: (comment: Comment) => void;
  onCommentBody: (postId: number, body: string) => void;
  onSendComment: (cardId: number, postId: number) => void;
  onToggleComments: (postId: number) => void;
}) {
  const selectedFilter = feedFilters.find(filter => filter.value === view) || feedFilters[0];

  return <>
    <View style={styles.feedLabelRow}><Text style={styles.feedLabel}>{busy.startsWith('feed-') ? 'Loading…' : selectedFilter.label}</Text><Text style={styles.feedLabelDetail}>{selectedFilter.detail}</Text></View>
    {data.posts.length ? data.posts.map(post => <PostCard
      key={post.id}
      post={post}
      busy={busy}
      commentBody={commentBodies[post.id] || ''}
      expanded={!!expandedComments[post.id]}
      onReact={() => onReact(post)}
      onShare={() => onShare(post)}
      viewerId={data.me.id}
      onOptions={() => onOptions(post)}
      onCommentOptions={onCommentOptions}
      onCommentBody={body => onCommentBody(post.id, body)}
      onSendComment={() => onSendComment(post.id, post.interaction_post_id)}
      onToggleComments={() => onToggleComments(post.id)}
    />) : <Empty title={view === 'all' ? 'Your circle is quiet' : 'Nothing here yet'} detail={view === 'all' ? 'Connect with drivers in People. Their posts will appear here, while your posts stay in My posts.' : 'Updates for this view will appear here.'} />}
  </>;
}

function PostCard({ post, viewerId, busy, commentBody, expanded, onReact, onShare, onOptions, onCommentOptions, onCommentBody, onSendComment, onToggleComments }: { post: CommunityPost; viewerId: number; busy: string; commentBody: string; expanded: boolean; onReact: () => void; onShare: () => void; onOptions: () => void; onCommentOptions: (comment: Comment) => void; onCommentBody: (body: string) => void; onSendComment: () => void; onToggleComments: () => void }) {
  const comments = expanded ? post.comments : post.comments.slice(-1);
  return <Card style={styles.post}>
    <View style={styles.postHead}>
      <Avatar user={post.author} />
      <View style={{ flex: 1 }}><Text style={styles.author}>{post.author.name}</Text><Text style={styles.meta}>@{post.author.username} · {relativeTime(post.created_at)}</Text></View>
      <Pressable accessibilityLabel="Post options" onPress={onOptions} style={styles.moreButton}><SymbolView name={{ ios: 'ellipsis', android: 'ellipsis', web: 'ellipsis' } as any} tintColor={palette.muted} size={20} /></Pressable>
    </View>

    {post.body ? <Text style={styles.postBody}>{post.body}</Text> : null}
    {post.shared_post ? <SharedPost post={post.shared_post} /> : <PostContent post={post} />}

    {(post.reaction_count || post.comments.length || post.share_count) ? <View style={styles.engagementSummary}>
      <Text style={styles.engagementText}>{post.reaction_count ? `👍 ${post.reaction_count}` : ''}</Text>
      <Text style={styles.engagementText}>{[post.comments.length ? `${post.comments.length} comment${post.comments.length === 1 ? '' : 's'}` : '', post.share_count ? `${post.share_count} share${post.share_count === 1 ? '' : 's'}` : ''].filter(Boolean).join(' · ')}</Text>
    </View> : null}

    <View style={styles.actionRow}>
      <PostAction symbol={post.reacted_by_me ? 'hand.thumbsup.fill' : 'hand.thumbsup'} label={post.reacted_by_me ? 'Liked' : 'Like'} active={post.reacted_by_me} busy={busy === `react-${post.id}`} onPress={onReact} />
      <PostAction symbol="bubble.left" label="Comment" active={expanded} onPress={onToggleComments} />
      <PostAction symbol="arrowshape.turn.up.right" label={busy === `share-${post.id}` ? 'Sharing…' : 'Share'} disabled={post.is_owner || busy === `share-${post.id}`} onPress={onShare} />
    </View>

    {comments.map(comment => <View key={comment.id} style={styles.comment}><Avatar user={comment.author} size={30} /><View style={styles.commentBubble}><View style={styles.commentHead}><Text style={styles.commentAuthor}>{comment.author.name} <Text style={styles.commentTime}>@{comment.author.username} · {relativeTime(comment.created_at)}</Text></Text>{comment.author.id !== viewerId ? <Pressable accessibilityLabel="Comment options" onPress={() => onCommentOptions(comment)} style={styles.commentOptions}><SymbolView name={{ ios: 'ellipsis', android: 'ellipsis', web: 'ellipsis' } as any} tintColor={palette.muted} size={15} /></Pressable> : null}</View><Text style={styles.commentBody}>{comment.body}</Text></View></View>)}
    {post.comments.length > 1 ? <Pressable onPress={onToggleComments}><Text style={styles.commentToggle}>{expanded ? 'Show less' : `View all ${post.comments.length} comments`}</Text></Pressable> : null}
    {expanded ? <View style={styles.commentForm}><Field value={commentBody} maxLength={400} onChangeText={onCommentBody} placeholder="Write a comment…" style={styles.commentField} onSubmitEditing={onSendComment} /><Pressable disabled={!commentBody.trim() || busy === `comment-${post.id}`} onPress={onSendComment} style={[styles.sendButton, (!commentBody.trim() || busy === `comment-${post.id}`) && styles.disabled]}><SymbolView name={{ ios: 'arrow.up', android: 'arrow.up', web: 'arrow.up' } as any} tintColor="white" size={16} /></Pressable></View> : null}
  </Card>;
}

function PostAction({ symbol, label, active = false, busy = false, disabled = false, onPress }: { symbol: string; label: string; active?: boolean; busy?: boolean; disabled?: boolean; onPress: () => void }) {
  return <Pressable disabled={disabled || busy} onPress={onPress} style={({ pressed }) => [styles.postAction, (disabled || busy) && styles.disabled, pressed && styles.pressed]}>
    <SymbolView name={{ ios: symbol, android: symbol, web: symbol } as any} tintColor={active ? palette.accent : palette.muted} size={18} />
    <Text style={[styles.postActionText, active && styles.postActionTextActive]}>{busy ? '…' : label}</Text>
  </Pressable>;
}

function SharedPost({ post }: { post: CommunityPost }) {
  return <View style={styles.sharedPost}>
    <View style={styles.sharedHead}><Avatar user={post.author} size={34} /><View style={{ flex: 1 }}><Text style={styles.sharedAuthor}>{post.author.name}</Text><Text style={styles.meta}>@{post.author.username} · {relativeTime(post.created_at)}</Text></View></View>
    {post.body ? <Text style={styles.sharedBody}>{post.body}</Text> : null}
    <PostContent post={post} nested />
  </View>;
}

function PostContent({ post, nested = false }: { post: CommunityPost; nested?: boolean }) {
  return <>
    {post.image_url ? <Image source={{ uri: post.image_url }} style={[styles.postImage, nested && styles.nestedImage]} /> : null}
    {post.event ? <Pressable onPress={() => router.push(`/event/${post.event!.id}`)} style={styles.attachment}><View style={styles.attachmentIcon}><SymbolView name={{ ios: 'flag.checkered', android: 'flag.checkered', web: 'flag.checkered' } as any} tintColor={palette.accent} size={19} /></View><View style={{ flex: 1 }}><Text style={styles.attachmentLabel}>{post.run ? 'SHARED RUN' : 'EVENT'}</Text><Text style={styles.attachmentTitle}>{post.event.name}</Text><Text style={styles.attachmentDetail}>{eventDate(post.event.date)} · {post.event.track.name}</Text></View><Text style={styles.arrow}>›</Text></Pressable> : null}
    {post.run?.drivers.length ? <View style={styles.runDrivers}><Text style={styles.runLabel}>Drivers in this run</Text><Text style={styles.runNames} numberOfLines={2}>{post.run.drivers.map(driver => driver.name).join(' · ')}</Text></View> : null}
    {post.car ? <View style={styles.attachment}><View style={[styles.attachmentIcon, styles.carIcon]}><SymbolView name={{ ios: 'car.fill', android: 'car.fill', web: 'car.fill' } as any} tintColor={palette.accent} size={19} /></View><View style={{ flex: 1 }}><Text style={styles.attachmentLabel}>GARAGE</Text><Text style={styles.attachmentTitle}>{post.car.label}</Text>{post.car.color ? <Text style={styles.attachmentDetail}>{post.car.color}</Text> : null}</View></View> : null}
  </>;
}

function EventsViewContent({ data }: { data: CommunityPayload }) {
  return <View style={styles.pageSection}>
    <View><Text style={styles.pageTitle}>Coming up</Text><Text style={styles.pageSubtitle}>See where your circle is headed next.</Text></View>
    {data.events.length ? data.events.map(item => <Pressable key={item.event.id} onPress={() => router.push(`/event/${item.event.id}`)} style={({ pressed }) => [styles.eventCard, pressed && styles.pressed]}>
      <View style={styles.eventDateBadge}><Text style={styles.eventDay}>{new Date(`${item.event.date}T12:00:00`).getDate()}</Text><Text style={styles.eventMonth}>{new Date(`${item.event.date}T12:00:00`).toLocaleString('en-US', { month: 'short' }).toUpperCase()}</Text></View>
      <View style={{ flex: 1 }}><Text style={styles.eventName}>{item.event.name}</Text><Text style={styles.eventTrack}>{item.event.track.name}</Text><View style={styles.goingRow}><View style={styles.avatarStack}>{item.circle_attendees.slice(0, 4).map((user, index) => <View key={user.id} style={{ marginLeft: index ? -8 : 0, zIndex: 4 - index }}><Avatar user={user} size={28} /></View>)}</View><Text style={styles.goingText}>{item.going_count} going</Text></View></View>
      <Text style={styles.arrow}>›</Text>
    </Pressable>) : <Empty title="No upcoming events" detail="Public track events will appear here." />}
  </View>;
}

function PeopleViewContent({ data, query, busy, onQuery, onConnect, onAccept, onRemove, onBlock, onUnblock }: { data: CommunityPayload; query: string; busy: string; onQuery: (query: string) => void; onConnect: (userId: number) => void; onAccept: (connectionId: number) => void; onRemove: (connection: Connection) => void; onBlock: (user: CommunityUser) => void; onUnblock: (user: CommunityUser) => void }) {
  const sections = useMemo(() => [{ title: query.trim() ? 'Search results' : 'People you may know', rows: data.suggestions }], [data.suggestions, query]);
  return <View style={styles.pageSection}>
    <View><Text style={styles.pageTitle}>Find your people</Text><Text style={styles.pageSubtitle}>Only accepted connections appear in your Circle feed.</Text></View>
    <Field value={query} onChangeText={onQuery} autoCapitalize="none" autoCorrect={false} placeholder="Search drivers as you type" />
    {data.received_requests.length ? <View style={styles.peopleSection}><SectionTitle title={`Requests (${data.received_requests.length})`} />{data.received_requests.map(connection => <PersonRow key={connection.id} user={connection.user} detail="Wants to connect" primary="Accept" secondary="Decline" tertiary="Block" busy={busy === `connection-${connection.id}`} onPrimary={() => onAccept(connection.id)} onSecondary={() => onRemove(connection)} onTertiary={() => onBlock(connection.user)} />)}</View> : null}
    {sections.map(section => <View key={section.title} style={styles.peopleSection}><SectionTitle title={section.title} />{section.rows.length ? section.rows.map(item => <PersonRow key={item.user.id} user={item.user} detail={item.reason} primary="Connect" secondary="Block" busy={busy === `user-${item.user.id}` || busy === `block-${item.user.id}`} onPrimary={() => onConnect(item.user.id)} onSecondary={() => onBlock(item.user)} dangerSecondary />) : <Empty title={query.trim() ? 'No drivers found' : 'No suggestions yet'} detail={query.trim() ? 'Try another username or name.' : 'Shared events and followed tracks will help find familiar drivers.'} />}</View>)}
    <View style={styles.peopleSection}><SectionTitle title={`Your circle (${data.connections.length})`} />{data.connections.length ? data.connections.map(connection => <PersonRow key={connection.id} user={connection.user} detail="Connected" secondary="Remove" tertiary="Block" busy={busy === `connection-${connection.id}` || busy === `block-${connection.user.id}`} onSecondary={() => onRemove(connection)} onTertiary={() => onBlock(connection.user)} />) : <Empty title="No connections yet" detail="Find a driver above and send your first request." />}</View>
    {data.sent_requests.length ? <View style={styles.peopleSection}><SectionTitle title="Pending" />{data.sent_requests.map(connection => <PersonRow key={connection.id} user={connection.user} detail="Request sent" secondary="Cancel" tertiary="Block" busy={busy === `connection-${connection.id}` || busy === `block-${connection.user.id}`} onSecondary={() => onRemove(connection)} onTertiary={() => onBlock(connection.user)} />)}</View> : null}
    {(data.blocked_users || []).length ? <View style={styles.peopleSection}><SectionTitle title="Blocked accounts" />{data.blocked_users.map(user => <PersonRow key={user.id} user={user} detail="Hidden from your Community" secondary="Unblock" busy={busy === `unblock-${user.id}`} onSecondary={() => onUnblock(user)} />)}</View> : null}
  </View>;
}

function ActivityViewContent({ data, busy, onAccept, onRemove, onOpenPost }: { data: CommunityPayload; busy: string; onAccept: (connectionId: number) => void; onRemove: (connection: Connection) => void; onOpenPost: () => void }) {
  const activity = data.activity || [];
  return <View style={styles.pageSection}>
    <View><Text style={styles.pageTitle}>Activity</Text><Text style={styles.pageSubtitle}>Requests and interactions from people in your circle.</Text></View>
    {data.received_requests.length ? <View style={styles.peopleSection}><SectionTitle title="Friend requests" />{data.received_requests.map(connection => <PersonRow key={connection.id} user={connection.user} detail="Wants to connect" primary="Accept" secondary="Decline" busy={busy === `connection-${connection.id}`} onPrimary={() => onAccept(connection.id)} onSecondary={() => onRemove(connection)} />)}</View> : null}
    <SectionTitle title="Recent activity" />
    {activity.length ? activity.map(item => <Pressable key={item.id} onPress={onOpenPost} style={({ pressed }) => [styles.activityRow, pressed && styles.pressed]}>
      <Avatar user={item.actor} size={42} />
      <View style={{ flex: 1 }}><Text style={styles.activityText}><Text style={styles.activityName}>{item.actor.name}</Text> {item.type === 'comment' ? 'commented on your post' : item.type === 'reaction' ? 'liked your post' : 'shared your post'}</Text>{item.type === 'comment' && item.detail ? <Text numberOfLines={2} style={styles.activityDetail}>“{item.detail}”</Text> : null}<Text style={styles.activityTime}>{relativeTime(item.created_at)}</Text></View>
      <Text style={styles.arrow}>›</Text>
    </Pressable>) : <Empty title="No new activity" detail="Friend requests, reactions, comments, and shares will appear here." />}
  </View>;
}

function PersonRow({ user, detail, primary, secondary, tertiary, dangerSecondary = false, busy, onPrimary, onSecondary, onTertiary }: { user: CommunityUser; detail: string; primary?: string; secondary?: string; tertiary?: string; dangerSecondary?: boolean; busy: boolean; onPrimary?: () => void; onSecondary?: () => void; onTertiary?: () => void }) {
  return <Card style={styles.personRow}><Avatar user={user} /><View style={{ flex: 1 }}><Text style={styles.personName}>{user.name}</Text><Text style={styles.personHandle}>@{user.username} · {detail}</Text></View><View style={styles.personActions}>{primary ? <Pressable disabled={busy} onPress={onPrimary} style={[styles.smallPrimary, busy && styles.disabled]}><Text style={styles.smallPrimaryText}>{busy ? '…' : primary}</Text></Pressable> : null}<View style={styles.personMinorActions}>{secondary ? <Pressable disabled={busy} onPress={onSecondary}><Text style={[styles.secondaryAction, dangerSecondary && styles.dangerAction]}>{secondary}</Text></Pressable> : null}{tertiary ? <Pressable disabled={busy} onPress={onTertiary}><Text style={styles.dangerAction}>{tertiary}</Text></Pressable> : null}</View></View></Card>;
}

function ComposerModal({ visible, me, body, image, busy, onBody, onPhoto, onRemovePhoto, onClose, onPublish }: { visible: boolean; me: CommunityUser; body: string; image: { uri: string; dataUrl: string } | null; busy: boolean; onBody: (body: string) => void; onPhoto: () => void; onRemovePhoto: () => void; onClose: () => void; onPublish: () => void }) {
  const disabled = busy || (!body.trim() && !image);
  return <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
    <SafeAreaView style={styles.modalScreen}>
      <View style={styles.modalHeader}><Pressable onPress={onClose}><Text style={styles.modalCancel}>Cancel</Text></Pressable><Text style={styles.modalTitle}>Create post</Text><Pressable disabled={disabled} onPress={onPublish} style={[styles.modalPost, disabled && styles.disabled]}><Text style={styles.modalPostText}>{busy ? 'Posting…' : 'Post'}</Text></Pressable></View>
      <ScrollView contentContainerStyle={styles.modalContent} keyboardShouldPersistTaps="handled">
        <View style={styles.composerIdentity}><Avatar user={me} /><View><Text style={styles.author}>{me.name}</Text><Text style={styles.meta}>Sharing with your circle</Text></View></View>
        <Field autoFocus multiline maxLength={600} value={body} onChangeText={onBody} placeholder="What’s happening at the track?" style={styles.modalField} />
        {image ? <View><Image source={{ uri: image.uri }} style={styles.preview} /><Pressable onPress={onRemovePhoto} style={styles.removePhoto}><Text style={styles.removePhotoText}>Remove photo</Text></Pressable></View> : null}
        <Pressable onPress={onPhoto} style={styles.addPhotoRow}><View style={styles.addPhotoIcon}><SymbolView name={{ ios: 'photo.fill', android: 'photo.fill', web: 'photo.fill' } as any} tintColor={palette.accent} size={20} /></View><View style={{ flex: 1 }}><Text style={styles.addPhotoTitle}>Add a photo</Text><Text style={styles.addPhotoDetail}>Show the car, paddock, or moment.</Text></View><Text style={styles.arrow}>›</Text></Pressable>
        <Text style={styles.guidelineText}>By posting, you agree to the <Text accessibilityRole="link" onPress={() => Linking.openURL(`${(process.env.EXPO_PUBLIC_API_URL || 'https://carbook.root-dynamics.com').replace(/\/$/, '')}/community-guidelines`)} style={styles.guidelineLink}>Community Guidelines</Text>.</Text>
      </ScrollView>
    </SafeAreaView>
  </Modal>;
}

export default function CommunityScreen() {
  return <CommunityExperience />;
}

const styles = StyleSheet.create({
  instagramHeader: { minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: palette.line, paddingBottom: 10 },
  instagramTitleRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  backToTrack: { minHeight: 38, flexDirection: 'row', alignItems: 'center', gap: 3 },
  backToTrackText: { color: palette.accent, fontSize: 13, fontWeight: '800' },
  instagramTitle: { color: palette.ink, fontSize: 27, fontWeight: '900', letterSpacing: -.6 },
  instagramActions: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  instagramAction: { position: 'relative', width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  instagramActionActive: { backgroundColor: palette.accentSoft },
  headerBadge: { position: 'absolute', top: 1, right: 0, minWidth: 16, height: 16, borderRadius: 8, paddingHorizontal: 3, backgroundColor: palette.primary, borderWidth: 2, borderColor: palette.canvas, alignItems: 'center', justifyContent: 'center' },
  headerBadgeText: { color: 'white', fontSize: 8, fontWeight: '900' },
  shortcutScroller: { height: 87, maxHeight: 87, marginHorizontal: -18 },
  shortcuts: { gap: 13, paddingHorizontal: 18, paddingBottom: 8 },
  shortcut: { width: 62, alignItems: 'center', gap: 5 },
  shortcutRing: { position: 'relative', width: 60, height: 60, borderRadius: 30, padding: 3, borderWidth: 2, borderColor: palette.line, alignItems: 'center', justifyContent: 'center' },
  shortcutRingActive: { borderColor: palette.accent },
  shortcutIcon: { width: 50, height: 50, borderRadius: 25, backgroundColor: palette.surfaceRaised, alignItems: 'center', justifyContent: 'center' },
  shortcutIconActive: { backgroundColor: palette.navy },
  shortcutLabel: { color: palette.muted, fontSize: 10, fontWeight: '700', textAlign: 'center' },
  shortcutLabelActive: { color: palette.ink, fontWeight: '900' },
  shortcutBadge: { position: 'absolute', top: -4, right: -5, minWidth: 18, height: 18, borderRadius: 9, paddingHorizontal: 3, backgroundColor: palette.primary, borderWidth: 2, borderColor: palette.canvas, alignItems: 'center', justifyContent: 'center' },
  shortcutBadgeText: { color: 'white', fontSize: 8, fontWeight: '900' },
  error: { padding: 13, borderRadius: 13, backgroundColor: palette.redSoft },
  errorText: { color: palette.red, fontWeight: '800', lineHeight: 19 },
  feedLabelRow: { gap: 2, paddingTop: 1 },
  feedLabel: { color: palette.ink, fontSize: 17, fontWeight: '900' },
  feedLabelDetail: { color: palette.muted, fontSize: 11 },
  post: { gap: 12, padding: 14, borderRadius: 16 },
  postHead: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  author: { color: palette.ink, fontWeight: '900', fontSize: 14 },
  meta: { color: palette.muted, fontSize: 10, marginTop: 2 },
  moreButton: { width: 38, height: 38, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  postBody: { color: palette.ink, fontSize: 15, lineHeight: 22 },
  postImage: { width: '100%', height: 265, borderRadius: 14, backgroundColor: palette.canvas },
  nestedImage: { height: 200, borderRadius: 10 },
  sharedPost: { borderWidth: 1, borderColor: palette.line, borderRadius: 14, padding: 11, gap: 10, backgroundColor: palette.surfaceRaised },
  sharedHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sharedAuthor: { color: palette.ink, fontSize: 12, fontWeight: '900' },
  sharedBody: { color: palette.ink, fontSize: 13, lineHeight: 19 },
  engagementSummary: { minHeight: 24, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: palette.line, paddingBottom: 8 },
  engagementText: { color: palette.muted, fontSize: 11 },
  actionRow: { flexDirection: 'row', alignItems: 'center', minHeight: 38, borderBottomWidth: 1, borderBottomColor: palette.line },
  postAction: { flex: 1, minHeight: 38, flexDirection: 'row', gap: 6, alignItems: 'center', justifyContent: 'center' },
  postActionText: { color: palette.muted, fontSize: 12, fontWeight: '800' },
  postActionTextActive: { color: palette.accent },
  attachment: { borderWidth: 1, borderColor: palette.line, backgroundColor: palette.surfaceRaised, borderRadius: 14, padding: 11, flexDirection: 'row', alignItems: 'center', gap: 10 },
  attachmentIcon: { width: 39, height: 39, borderRadius: 12, backgroundColor: palette.accentSoft, alignItems: 'center', justifyContent: 'center' },
  carIcon: { backgroundColor: palette.surfaceRaised },
  attachmentLabel: { color: palette.accent, fontSize: 9, letterSpacing: 1, fontWeight: '900' },
  attachmentTitle: { color: palette.ink, fontSize: 14, fontWeight: '900', marginTop: 2 },
  attachmentDetail: { color: palette.muted, fontSize: 11, marginTop: 2 },
  runDrivers: { backgroundColor: palette.accentSoft, borderRadius: 12, padding: 11 },
  runLabel: { color: palette.accent, fontSize: 10, fontWeight: '900', textTransform: 'uppercase' },
  runNames: { color: palette.ink, fontSize: 12, lineHeight: 18, fontWeight: '700', marginTop: 3 },
  comment: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  commentBubble: { flex: 1, backgroundColor: palette.canvas, borderRadius: 13, paddingHorizontal: 11, paddingVertical: 8 },
  commentHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 7 },
  commentOptions: { width: 28, height: 24, alignItems: 'center', justifyContent: 'center' },
  commentAuthor: { color: palette.ink, fontSize: 11, fontWeight: '900' },
  commentTime: { color: palette.muted, fontWeight: '600' },
  commentBody: { color: palette.ink, fontSize: 13, lineHeight: 18, marginTop: 2 },
  commentToggle: { color: palette.accent, fontSize: 12, fontWeight: '800' },
  commentForm: { flexDirection: 'row', gap: 8, alignItems: 'center' },
  commentField: { flex: 1, height: 44, fontSize: 14 },
  sendButton: { width: 42, height: 42, borderRadius: 13, backgroundColor: palette.primary, alignItems: 'center', justifyContent: 'center' },
  pageSection: { gap: 12 },
  pageTitle: { color: palette.ink, fontSize: 22, fontWeight: '900' },
  pageSubtitle: { color: palette.muted, fontSize: 12, lineHeight: 18, marginTop: 3 },
  eventCard: { minHeight: 100, borderRadius: 17, padding: 13, flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: palette.surface, borderWidth: 1, borderColor: palette.line, ...shadow },
  eventDateBadge: { width: 55, height: 61, borderRadius: 14, backgroundColor: palette.accentSoft, alignItems: 'center', justifyContent: 'center' },
  eventDay: { color: palette.accent, fontSize: 22, fontWeight: '900' },
  eventMonth: { color: palette.accent, fontSize: 9, fontWeight: '900' },
  eventName: { color: palette.ink, fontSize: 16, fontWeight: '900' },
  eventTrack: { color: palette.muted, fontSize: 11, marginTop: 3 },
  goingRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 9 },
  avatarStack: { flexDirection: 'row' },
  goingText: { color: palette.muted, fontSize: 10, fontWeight: '700' },
  peopleSection: { gap: 9 },
  personRow: { padding: 12, flexDirection: 'row', alignItems: 'center', gap: 10 },
  personName: { color: palette.ink, fontWeight: '900', fontSize: 13 },
  personHandle: { color: palette.muted, fontSize: 10, marginTop: 3 },
  personActions: { alignItems: 'flex-end', gap: 5 },
  personMinorActions: { flexDirection: 'row', gap: 9 },
  smallPrimary: { minWidth: 70, minHeight: 34, borderRadius: 10, backgroundColor: palette.primary, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 9 },
  smallPrimaryText: { color: 'white', fontWeight: '900', fontSize: 11 },
  secondaryAction: { color: palette.muted, fontSize: 10, fontWeight: '800', paddingHorizontal: 5, paddingVertical: 3 },
  dangerAction: { color: palette.red, fontSize: 10, fontWeight: '800', paddingHorizontal: 5, paddingVertical: 3 },
  activityRow: { borderRadius: 16, padding: 12, flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: palette.surface, borderWidth: 1, borderColor: palette.line },
  activityText: { color: palette.ink, fontSize: 13, lineHeight: 18 },
  activityName: { fontWeight: '900' },
  activityDetail: { color: palette.muted, fontSize: 11, lineHeight: 16, marginTop: 3 },
  activityTime: { color: palette.accent, fontSize: 10, fontWeight: '800', marginTop: 4 },
  modalScreen: { flex: 1, backgroundColor: palette.canvas },
  modalHeader: { minHeight: 62, paddingHorizontal: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: palette.line, backgroundColor: palette.surface },
  modalCancel: { color: palette.muted, fontSize: 14, fontWeight: '800' },
  modalTitle: { color: palette.ink, fontSize: 17, fontWeight: '900' },
  modalPost: { minWidth: 70, height: 38, borderRadius: 11, backgroundColor: palette.primary, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 12 },
  modalPostText: { color: 'white', fontSize: 12, fontWeight: '900' },
  modalContent: { padding: 18, gap: 16 },
  composerIdentity: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  modalField: { minHeight: 145, height: 145, paddingTop: 15, textAlignVertical: 'top', fontSize: 18, borderWidth: 0, backgroundColor: 'transparent' },
  preview: { width: '100%', height: 245, borderRadius: 15, backgroundColor: palette.canvas },
  removePhoto: { position: 'absolute', top: 10, right: 10, backgroundColor: 'rgba(16,24,40,.82)', borderRadius: 999, paddingHorizontal: 11, paddingVertical: 7 },
  removePhotoText: { color: 'white', fontWeight: '800', fontSize: 11 },
  addPhotoRow: { borderRadius: 16, padding: 13, flexDirection: 'row', alignItems: 'center', gap: 11, backgroundColor: palette.surface, borderWidth: 1, borderColor: palette.line },
  addPhotoIcon: { width: 42, height: 42, borderRadius: 13, backgroundColor: palette.accentSoft, alignItems: 'center', justifyContent: 'center' },
  addPhotoTitle: { color: palette.ink, fontSize: 14, fontWeight: '900' },
  addPhotoDetail: { color: palette.muted, fontSize: 11, marginTop: 2 },
  guidelineText: { color: palette.muted, fontSize: 11, lineHeight: 17, textAlign: 'center', paddingHorizontal: 18 },
  guidelineLink: { color: palette.accent, fontWeight: '800' },
  avatar: { backgroundColor: palette.accentSoft, overflow: 'hidden', alignItems: 'center', justifyContent: 'center', borderWidth: 2, borderColor: 'white' },
  avatarImage: { width: '100%', height: '100%' },
  avatarText: { color: palette.accent, fontWeight: '900' },
  arrow: { color: palette.accent, fontSize: 25 },
  pressed: { opacity: .65 },
  disabled: { opacity: .42 },
});
