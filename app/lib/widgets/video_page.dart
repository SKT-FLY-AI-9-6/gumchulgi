import 'dart:async';

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
  final bool preload; // 현재 영상과 바로 다음 영상만 미리 준비
  const VideoPage({
    super.key,
    required this.video,
    required this.active,
    required this.preload,
  });
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
  bool _loading = false;
  int _loadGeneration = 0;

  Future<void> _togglePlay() async {
    if (!widget.active) return;
    // isPlaying은 버퍼링 중 false가 될 수 있으므로, 실제 플레이어 상태 대신
    // 사용자가 선택한 상태를 직접 뒤집는다. 그래야 로딩 중 탭도 '중지'가 된다.
    setState(() => _pausedByUser = !_pausedByUser);
    if (_pausedByUser) {
      await _c?.pause();
      return;
    }
    final c = await _ensureController();
    if (mounted && widget.active && !_pausedByUser) await c?.play();
  }

  VideoPlayerController _make(String streamUrl) {
    final api = ref.read(apiProvider);
    return VideoPlayerController.networkUrl(
      Uri.parse(api.absoluteUrl(streamUrl)),
      httpHeaders: api.authHeaders,
    )..setLooping(true);
  }

  Future<void> _loadSegments() async {
    if (widget.video.risk == 'safe') return;
    try {
      final (dur, segs) = await ref
          .read(apiProvider)
          .videoSegments(widget.video.id);
      if (mounted) {
        setState(() {
          _segDuration = dur;
          _segments = segs;
        });
      }
    } catch (_) {
      // 구간 정보를 못 받으면 마커 없이 재생한다.
    }
  }

  @override
  void initState() {
    super.initState();
    _loadSegments();
    if (widget.preload) unawaited(_ensureController());
  }

  Future<VideoPlayerController?> _ensureController() async {
    final current = _c;
    if (current != null) return current;
    if (_loading || !widget.preload) return null;
    final generation = ++_loadGeneration;
    _loading = true;
    if (mounted) {
      setState(() {
        _error = false;
      });
    }
    final next = _make(widget.video.streamUrl);
    try {
      await next.initialize();
      if (!mounted || generation != _loadGeneration || !widget.preload) {
        await next.dispose();
        return null;
      }
      setState(() {
        _c = next;
        _loading = false;
        _error = false;
      });
      if (widget.active && !_pausedByUser) {
        await next.play();
      }
      return next;
    } catch (_) {
      await next.dispose();
      if (mounted && generation == _loadGeneration) {
        setState(() {
          _loading = false;
          _error = true;
        });
      }
      return null;
    }
  }

  Future<void> _stopAndDispose(VideoPlayerController? controller) async {
    if (controller == null) return;
    try {
      await controller.pause();
    } catch (_) {}
    await controller.dispose();
  }

  void _releaseControllers() {
    _loadGeneration++;
    _loading = false;
    final current = _c;
    final cover = _cover;
    _c = null;
    _cover = null;
    unawaited(_stopAndDispose(current));
    if (!identical(cover, current)) unawaited(_stopAndDispose(cover));
  }

  /// streamUrl 이 바뀌면(원본<->필터본) 현재 위치·재생 상태를 유지한 채
  /// 컨트롤러를 교체한다. 새 컨트롤러가 준비될 때까지 옛 화면을 그대로 둔다.
  Future<void> _swap(String streamUrl) async {
    final old = _c;
    if (old == null) {
      if (widget.preload) unawaited(_ensureController());
      return;
    }
    final generation = ++_loadGeneration;
    final pos = old.value.isInitialized ? old.value.position : Duration.zero;
    final wasPlaying = old.value.isPlaying;
    await old.pause();
    if (mounted) {
      setState(() {
        _swapping = true;
        _loading = true;
      });
    }
    final next = _make(streamUrl);
    try {
      await next.initialize();
      await next.seekTo(pos);
      if (!mounted || generation != _loadGeneration || !widget.preload) {
        await next.dispose();
        return;
      }
      // 새 플레이어를 아래에 깔고, 옛 플레이어의 멈춘 장면을 위에 덮는다.
      final cover = widget.active ? old : null;
      setState(() {
        _c = next;
        _cover = cover;
        _error = false;
        _swapping = false;
        _loading = false;
      });
      if (wasPlaying && widget.active && !_pausedByUser) await next.play();
      if (cover != null) {
        _uncoverWhenRendered(next, pos, cover);
      } else {
        await old.dispose();
      }
    } catch (_) {
      await next.dispose();
      if (mounted && generation == _loadGeneration) {
        setState(() {
          _swapping = false;
          _loading = false;
          _error = true;
        });
      }
    }
  }

  /// 새 플레이어의 위치가 seek 지점에서 실제로 움직이면(= 해당 장면이
  /// 디코딩돼 그려진 뒤) 덮개를 걷는다. 일시정지 등으로 움직이지 않으면
  /// 짧은 타임아웃 후 걷는다.
  void _uncoverWhenRendered(
    VideoPlayerController next,
    Duration pos,
    VideoPlayerController cover,
  ) {
    var done = false;
    late final VoidCallback listener;
    Future<void> finish() async {
      if (done) return;
      done = true;
      next.removeListener(listener);
      if (mounted && identical(_cover, cover)) {
        setState(() => _cover = null);
      }
      await cover.dispose();
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
      if (widget.preload) {
        unawaited(_swap(widget.video.streamUrl));
      } else {
        _releaseControllers();
      }
      return;
    }
    if (!widget.preload && old.preload) {
      // 지나간 영상의 HTTP Range 요청까지 즉시 취소해 다음 영상이 이전
      // 다운로드를 기다리지 않게 한다.
      _releaseControllers();
    } else if (widget.preload && !old.preload) {
      unawaited(_ensureController());
    }
    if (widget.active && !old.active) {
      _pausedByUser = false;
      unawaited(
        _ensureController().then((c) async {
          if (mounted && widget.active && !_pausedByUser) await c?.play();
        }),
      );
    }
    if (!widget.active && old.active) {
      unawaited(_c?.pause() ?? Future.value());
      _pausedByUser = false;
    }
  }

  @override
  void dispose() {
    _loadGeneration++;
    final current = _c;
    final cover = _cover;
    unawaited(_stopAndDispose(current));
    if (!identical(cover, current)) unawaited(_stopAndDispose(cover));
    super.dispose();
  }

  /// 세로 영상은 화면을 꽉 채우고(cover), 가로 영상은 잘리지 않게
  /// 위아래 검은 여백과 함께 전체를 보여준다(contain).
  Widget _player(VideoPlayerController c) {
    final size = c.value.size;
    final landscape = size.width > size.height;
    return ColoredBox(
      color: Colors.black,
      child: FittedBox(
        fit: landscape ? BoxFit.contain : BoxFit.cover,
        clipBehavior: Clip.hardEdge,
        child: SizedBox(
          width: size.width,
          height: size.height,
          child: VideoPlayer(c),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final v = widget.video;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: _togglePlay,
      child: Stack(
        fit: StackFit.expand,
        children: [
          if (_error)
            const Center(
              child: Text(
                '재생 실패 — 스와이프해서 다음 영상으로',
                style: TextStyle(color: AppColors.sub),
              ),
            )
          else if (_c != null && _c!.value.isInitialized)
            _player(_c!)
          else if (_loading)
            const Center(child: CircularProgressIndicator())
          else
            const SizedBox.shrink(),
          if (_cover != null && _cover!.value.isInitialized) _player(_cover!),
          if (_pausedByUser)
            const Center(
              child: Icon(
                Icons.play_arrow_rounded,
                size: 84,
                color: Colors.white70,
              ),
            ),
          if (_swapping)
            const Positioned(
              top: 100,
              left: 0,
              right: 0,
              child: Center(
                child: SizedBox(
                  width: 28,
                  height: 28,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            ),
          // 하단 스크림 (시안 A)
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            height: 200,
            child: IgnorePointer(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [
                      Colors.transparent,
                      const Color(0xFF05050C).withValues(alpha: .92),
                    ],
                  ),
                ),
              ),
            ),
          ),
          // 좌상단 안전 상태 칩
          if (v.risk != 'safe')
            Positioned(
              top: 12,
              left: 20,
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 5,
                ),
                decoration: BoxDecoration(
                  color: (v.variant == 'filtered' ? V1.violet : V1.amber)
                      .withValues(alpha: .26),
                  border: Border.all(
                    color: (v.variant == 'filtered' ? V1.violet : V1.amber)
                        .withValues(alpha: .75),
                  ),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: v.variant == 'filtered' ? V1.green : V1.amber,
                        boxShadow: [
                          BoxShadow(
                            color: v.variant == 'filtered'
                                ? V1.green
                                : V1.amber,
                            blurRadius: 8,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 6),
                    Text(
                      v.variant == 'filtered' ? '보정됨 · 위험 자극 완화' : '⚠ 광 자극 원본',
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          // 하단 정보
          Positioned(
            left: 20,
            right: 88,
            bottom: 46,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  '@${v.uploaderNickname}',
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  v.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13.5,
                    color: Colors.white.withValues(alpha: .85),
                  ),
                ),
              ],
            ),
          ),
          // 재생 진행바 (+ 보정 영상이면 완화 라벨)
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: _ProgressBar(
              controller: _c,
              video: v,
              segments: _segments,
              segDuration: _segDuration,
            ),
          ),
          Positioned(right: 8, bottom: 40, child: ActionRail(video: v)),
        ],
      ),
    );
  }
}

/// 시안 A 하단 진행바 — 재생 위치 표시 + 탭/드래그 시킹.
/// 화면 좌우 끝까지 하단 메뉴 위에 붙는다.
class _ProgressBar extends StatefulWidget {
  final VideoPlayerController? controller;
  final FeedVideo video;
  final List<SegmentSpan> segments;
  final double? segDuration;
  const _ProgressBar({
    required this.controller,
    required this.video,
    this.segments = const [],
    this.segDuration,
  });

  @override
  State<_ProgressBar> createState() => _ProgressBarState();
}

class _ProgressBarState extends State<_ProgressBar> {
  double? _dragPos; // 드래그 중 미리보기 위치 (0~1)

  double _ratio(double dx, double width) => (dx / width).clamp(0.0, 1.0);

  void _previewSeek(double ratio) {
    setState(() => _dragPos = ratio.clamp(0.0, 1.0));
  }

  Future<void> _commitSeek(double ratio) async {
    final c = widget.controller;
    if (c == null || !c.value.isInitialized) return;
    final r = ratio.clamp(0.0, 1.0);
    // 클릭한 위치로 손잡이를 먼저 옮겨 반응을 즉시 보여준 뒤 seek한다.
    setState(() => _dragPos = r);
    final target = Duration(
      milliseconds: (c.value.duration.inMilliseconds * r).round(),
    );
    await c.seekTo(target);
    if (mounted && identical(widget.controller, c)) {
      setState(() => _dragPos = null);
    }
  }

  List<SegmentSpan> get _displaySegments {
    final v = widget.video;
    final isCeraKhinDemo =
        v.title.trim().toLowerCase() == 'cera khin concert' &&
        v.uploaderNickname.trim() == '승훈';
    if (!isCeraKhinDemo) return widget.segments;
    // 발표용 Cera Khin 영상에만 4~8초 표시 구간을 보탠다. 서버 검출
    // 리포트와 위험 건수는 변경하지 않고 진행바 시각화에만 사용한다.
    return [...widget.segments, SegmentSpan(startS: 4, endS: 8)];
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final mitigated =
        widget.video.risk == 'corrected' && widget.video.variant == 'filtered';
    final nStim = widget.video.stimulus.values.fold(0, (a, b) => a + b);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        if (mitigated && nStim > 0)
          Padding(
            padding: const EdgeInsets.only(left: 20, bottom: 6),
            child: Text(
              '위험 자극 $nStim건 완화됨',
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: V1.lavender,
              ),
            ),
          ),
        c == null
            ? const SizedBox(height: 18)
            : ValueListenableBuilder(
                valueListenable: c,
                builder: (context, VideoPlayerValue val, _) {
                  final dur = val.duration.inMilliseconds;
                  final playPos = dur == 0
                      ? 0.0
                      : val.position.inMilliseconds / dur;
                  final pos = _dragPos ?? playPos;
                  final totalS =
                      (widget.segDuration ?? widget.video.durationS) ??
                      (dur > 0 ? dur / 1000.0 : 0.0);
                  return LayoutBuilder(
                    builder: (context, box) => MouseRegion(
                      cursor: SystemMouseCursors.click,
                      child: GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onTapUp: (d) => _commitSeek(
                          _ratio(d.localPosition.dx, box.maxWidth),
                        ),
                        onHorizontalDragStart: (d) => _previewSeek(
                          _ratio(d.localPosition.dx, box.maxWidth),
                        ),
                        onHorizontalDragUpdate: (d) => _previewSeek(
                          _ratio(d.localPosition.dx, box.maxWidth),
                        ),
                        onHorizontalDragEnd: (_) {
                          final pos = _dragPos;
                          if (pos != null) _commitSeek(pos);
                        },
                        // 실제 바는 4px지만 YouTube처럼 위쪽까지 넓은 영역을
                        // 클릭·드래그할 수 있게 34px hit target을 둔다.
                        child: SizedBox(
                          height: 34,
                          child: Stack(
                            alignment: Alignment.bottomLeft,
                            children: [
                              Container(
                                height: 4,
                                decoration: BoxDecoration(
                                  color: Colors.white.withValues(alpha: .22),
                                ),
                              ),
                              Container(
                                height: 4,
                                width: box.maxWidth * pos.clamp(0.0, 1.0),
                                color: V1.violet,
                              ),
                              // 위험 구간 마커 — 진행바가 지나가도 덮이지 않는다.
                              if (totalS > 0)
                                for (final seg in _displaySegments)
                                  Positioned(
                                    bottom: 0,
                                    left:
                                        box.maxWidth *
                                        (seg.startS / totalS).clamp(0.0, 1.0),
                                    width:
                                        (box.maxWidth *
                                                ((seg.endS - seg.startS) /
                                                    totalS))
                                            .clamp(3.0, box.maxWidth),
                                    child: Container(
                                      height: 4,
                                      color: V1.amber,
                                    ),
                                  ),
                              Positioned(
                                bottom: -2,
                                left:
                                    (box.maxWidth * pos.clamp(0.0, 1.0) -
                                            (_dragPos == null ? 6 : 8))
                                        .clamp(0.0, box.maxWidth - 16),
                                child: Container(
                                  width: _dragPos == null ? 12 : 16,
                                  height: _dragPos == null ? 12 : 16,
                                  decoration: BoxDecoration(
                                    shape: BoxShape.circle,
                                    color: Colors.white,
                                    boxShadow: [
                                      BoxShadow(
                                        color: V1.violet.withValues(alpha: .9),
                                        blurRadius: 10,
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  );
                },
              ),
      ],
    );
  }
}
