import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../theme.dart';
import 'brand_v1.dart';
import 'action_rail.dart';

class VideoPage extends ConsumerStatefulWidget {
  final FeedVideo video;
  final bool active; // 현재 페이지일 때만 재생
  const VideoPage({super.key, required this.video, required this.active});
  @override
  ConsumerState<VideoPage> createState() => _VideoPageState();
}

class _VideoPageState extends ConsumerState<VideoPage> {
  VideoPlayerController? _c;
  bool _error = false;
  bool _swapping = false;
  double? _segDuration;
  List<SegmentSpan> _segments = const [];
  bool _pausedByUser = false; // 화면 탭으로 멈춘 상태
  // 교체 직후 새 플레이어가 실제 장면을 그릴 때까지 덮어 두는 옛 플레이어
  VideoPlayerController? _cover;

  void _togglePlay() {
    final c = _c;
    if (c == null || !c.value.isInitialized) return;
    setState(() {
      _pausedByUser = c.value.isPlaying;
      _pausedByUser ? c.pause() : c.play();
    });
  }

  VideoPlayerController _make(String streamUrl) {
    final api = ref.read(apiProvider);
    return VideoPlayerController.networkUrl(
        Uri.parse(api.absoluteUrl(streamUrl)),
        httpHeaders: api.authHeaders)
      ..setLooping(true);
  }

  Future<void> _loadSegments() async {
    if (widget.video.risk == 'safe') return;
    try {
      final (dur, segs) =
          await ref.read(apiProvider).videoSegments(widget.video.id);
      if (mounted) setState(() { _segDuration = dur; _segments = segs; });
    } catch (_) {
      // 구간 정보를 못 받으면 마커 없이 재생한다.
    }
  }

  @override
  void initState() {
    super.initState();
    _loadSegments();
    _c = _make(widget.video.streamUrl)
      ..initialize().then((_) {
        if (mounted) setState(() {});
        if (mounted && widget.active) _c!.play();
      }).catchError((_) {
        if (mounted) setState(() => _error = true);
      });
  }

  /// streamUrl 이 바뀌면(원본<->필터본) 현재 위치·재생 상태를 유지한 채
  /// 컨트롤러를 교체한다. 새 컨트롤러가 준비될 때까지 옛 화면을 그대로 둔다.
  Future<void> _swap(String streamUrl) async {
    final old = _c;
    final pos = old?.value.isInitialized == true
        ? old!.value.position : Duration.zero;
    final wasPlaying = old?.value.isPlaying ?? widget.active;
    old?.pause();
    setState(() => _swapping = true);
    final next = _make(streamUrl);
    try {
      await next.initialize();
      await next.seekTo(pos);
      if (!mounted) { await next.dispose(); return; }
      // 새 플레이어를 아래에 깔고, 옛 플레이어의 멈춘 장면을 위에 덮는다.
      setState(() { _c = next; _cover = old; _error = false; _swapping = false; });
      if (wasPlaying && widget.active && !_pausedByUser) await next.play();
      _uncoverWhenRendered(next, pos);
    } catch (_) {
      await next.dispose();
      if (mounted) setState(() { _swapping = false; _error = true; });
    }
  }

  /// 새 플레이어의 위치가 seek 지점에서 실제로 움직이면(= 해당 장면이
  /// 디코딩돼 그려진 뒤) 덮개를 걷는다. 일시정지 등으로 움직이지 않으면
  /// 짧은 타임아웃 후 걷는다.
  void _uncoverWhenRendered(VideoPlayerController next, Duration pos) {
    var done = false;
    late final VoidCallback listener;
    Future<void> finish() async {
      if (done) return;
      done = true;
      next.removeListener(listener);
      final cover = _cover;
      if (mounted) setState(() => _cover = null);
      await cover?.dispose();
    }
    listener = () {
      final p = next.value.position;
      if ((p - pos).abs() > const Duration(milliseconds: 60)) finish();
    };
    next.addListener(listener);
    Future.delayed(const Duration(milliseconds: 600), finish);
  }

  @override
  void didUpdateWidget(VideoPage old) {
    super.didUpdateWidget(old);
    if (widget.video.streamUrl != old.video.streamUrl) {
      _swap(widget.video.streamUrl);
      return;
    }
    if (widget.active && !old.active && !_pausedByUser) _c?.play();
    if (!widget.active && old.active) { _c?.pause(); _pausedByUser = false; }
  }

  @override
  void dispose() {
    _c?.dispose();
    _cover?.dispose();
    super.dispose();
  }

  /// 세로 영상은 화면을 꽉 채우고(cover), 가로 영상은 잘리지 않게
  /// 위아래 검은 여백과 함께 전체를 보여준다(contain).
  Widget _player(VideoPlayerController c) {
    final size = c.value.size;
    final landscape = size.width > size.height;
    return ColoredBox(color: Colors.black, child: FittedBox(
        fit: landscape ? BoxFit.contain : BoxFit.cover,
        clipBehavior: Clip.hardEdge,
        child: SizedBox(width: size.width, height: size.height,
            child: VideoPlayer(c))));
  }

  @override
  Widget build(BuildContext context) {
    final v = widget.video;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: _togglePlay,
      child: Stack(fit: StackFit.expand, children: [
      if (_error)
        const Center(child: Text('재생 실패 — 스와이프해서 다음 영상으로',
            style: TextStyle(color: AppColors.sub)))
      else if (_c != null && _c!.value.isInitialized)
        _player(_c!)
      else
        const Center(child: CircularProgressIndicator()),
      if (_cover != null && _cover!.value.isInitialized) _player(_cover!),
      if (_pausedByUser)
        const Center(child: Icon(Icons.play_arrow_rounded, size: 84,
            color: Colors.white70)),
      if (_swapping)
        const Positioned(top: 100, left: 0, right: 0,
            child: Center(child: SizedBox(width: 28, height: 28,
                child: CircularProgressIndicator(strokeWidth: 2)))),
      // 하단 스크림 (시안 A)
      Positioned(left: 0, right: 0, bottom: 0, height: 200,
          child: IgnorePointer(child: DecoratedBox(
              decoration: BoxDecoration(gradient: LinearGradient(
                  begin: Alignment.topCenter, end: Alignment.bottomCenter,
                  colors: [Colors.transparent,
                      const Color(0xFF05050C).withValues(alpha: .92)]))))),
      // 좌상단 안전 상태 칩
      if (v.risk != 'safe')
        Positioned(top: 12, left: 20, child: Container(
            padding: const EdgeInsets.symmetric(
                horizontal: 12, vertical: 5),
            decoration: BoxDecoration(
                color: (v.variant == 'filtered'
                        ? V1.violet : V1.amber).withValues(alpha: .26),
                border: Border.all(color: (v.variant == 'filtered'
                        ? V1.violet : V1.amber).withValues(alpha: .75)),
                borderRadius: BorderRadius.circular(20)),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Container(width: 8, height: 8, decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: v.variant == 'filtered' ? V1.green : V1.amber,
                  boxShadow: [BoxShadow(color: v.variant == 'filtered'
                      ? V1.green : V1.amber, blurRadius: 8)])),
              const SizedBox(width: 6),
              Text(v.variant == 'filtered'
                      ? '보정됨 · 위험 자극 완화' : '⚠ 광 자극 원본',
                  style: const TextStyle(fontSize: 12,
                      fontWeight: FontWeight.w600)),
            ]))),
      // 하단 정보
      Positioned(left: 20, right: 88, bottom: 46, child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('@${v.uploaderNickname}', style: const TextStyle(
              fontSize: 16, fontWeight: FontWeight.w700)),
          const SizedBox(height: 5),
          Text(v.title, maxLines: 2, overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 13.5,
                  color: Colors.white.withValues(alpha: .85))),
        ])),
      // 재생 진행바 (+ 보정 영상이면 완화 라벨)
      Positioned(left: 20, right: 20, bottom: 12, child:
          _ProgressBar(controller: _c, video: v,
              segments: _segments, segDuration: _segDuration)),
      Positioned(right: 8, bottom: 40, child: ActionRail(video: v)),
    ]));
  }
}


/// 시안 A 하단 진행바 — 재생 위치 + (보정 영상) 완화 안내 라벨
class _ProgressBar extends StatelessWidget {
  final VideoPlayerController? controller;
  final FeedVideo video;
  final List<SegmentSpan> segments;
  final double? segDuration;
  const _ProgressBar({required this.controller, required this.video,
      this.segments = const [], this.segDuration});

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final mitigated = video.risk == 'corrected' &&
        video.variant == 'filtered';
    final nStim = video.stimulus.values.fold(0, (a, b) => a + b);
    return Column(crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min, children: [
      if (mitigated && nStim > 0)
        Padding(padding: const EdgeInsets.only(bottom: 7),
            child: Text('위험 자극 $nStim건 완화됨',
                style: const TextStyle(fontSize: 11,
                    fontWeight: FontWeight.w600, color: V1.lavender))),
      SizedBox(height: 12, child: c == null
          ? const SizedBox.shrink()
          : ValueListenableBuilder(valueListenable: c,
              builder: (context, VideoPlayerValue val, _) {
                final dur = val.duration.inMilliseconds;
                final pos = dur == 0 ? 0.0
                    : val.position.inMilliseconds / dur;
                final totalS = (segDuration ?? video.durationS) ??
                    (dur > 0 ? dur / 1000.0 : 0.0);
                return LayoutBuilder(builder: (context, box) =>
                    Stack(alignment: Alignment.centerLeft, children: [
                  Container(height: 4, decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: .22),
                      borderRadius: BorderRadius.circular(2))),
                  Container(height: 4,
                      width: box.maxWidth * pos.clamp(0.0, 1.0),
                      decoration: BoxDecoration(color: V1.violet,
                          borderRadius: BorderRadius.circular(2))),
                  // 위험 구간 마커 (노란색) — 진행바가 지나가도
                  // 덮이지 않게 항상 위에 그린다.
                  if (totalS > 0)
                    for (final seg in segments)
                      Positioned(
                          left: box.maxWidth *
                              (seg.startS / totalS).clamp(0.0, 1.0),
                          width: (box.maxWidth *
                                  ((seg.endS - seg.startS) / totalS))
                              .clamp(3.0, box.maxWidth),
                          child: Container(height: 4,
                              decoration: BoxDecoration(
                                  color: V1.amber,
                                  borderRadius:
                                      BorderRadius.circular(2)))),
                  Positioned(
                      left: (box.maxWidth * pos.clamp(0.0, 1.0) - 6)
                          .clamp(0.0, box.maxWidth - 12),
                      child: Container(width: 12, height: 12,
                          decoration: BoxDecoration(
                              shape: BoxShape.circle, color: Colors.white,
                              boxShadow: [BoxShadow(
                                  color: V1.violet.withValues(alpha: .9),
                                  blurRadius: 10)]))),
                ]));
              })),
    ]);
  }
}
