import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../theme.dart';
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

  @override
  void initState() {
    super.initState();
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

  Widget _player(VideoPlayerController c) => FittedBox(
      fit: BoxFit.cover, clipBehavior: Clip.hardEdge,
      child: SizedBox(width: c.value.size.width,
          height: c.value.size.height, child: VideoPlayer(c)));

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
      // 하단 정보
      Positioned(left: 16, right: 88, bottom: 24, child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('@${v.uploaderNickname}',
              style: const TextStyle(fontWeight: FontWeight.bold)),
          Text(v.title, maxLines: 2, overflow: TextOverflow.ellipsis),
          if (v.risk != 'safe')
            Container(
              margin: const EdgeInsets.only(top: 6),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                  color: v.variant == 'filtered'
                      ? AppColors.blue.withValues(alpha: .25)
                      : AppColors.amber.withValues(alpha: .25),
                  borderRadius: BorderRadius.circular(6)),
              child: Text(v.variant == 'filtered'
                  ? '보호 필터 적용됨' : '⚠ 광 자극 원본',
                  style: const TextStyle(fontSize: 12))),
        ])),
      Positioned(right: 8, bottom: 24, child: ActionRail(video: v)),
    ]));
  }
}
