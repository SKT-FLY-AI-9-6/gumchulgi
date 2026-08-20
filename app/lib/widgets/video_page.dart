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

  @override
  void initState() {
    super.initState();
    final api = ref.read(apiProvider);
    _c = VideoPlayerController.networkUrl(
        Uri.parse(api.absoluteUrl(widget.video.streamUrl)),
        httpHeaders: api.authHeaders)
      ..setLooping(true)
      ..initialize().then((_) {
        if (mounted) setState(() {});
        if (mounted && widget.active) _c!.play();
      }).catchError((_) {
        if (mounted) setState(() => _error = true);
      });
  }

  @override
  void didUpdateWidget(VideoPage old) {
    super.didUpdateWidget(old);
    if (widget.active && !old.active) _c?.play();
    if (!widget.active && old.active) _c?.pause();
  }

  @override
  void dispose() {
    _c?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final v = widget.video;
    return Stack(fit: StackFit.expand, children: [
      if (_error)
        const Center(child: Text('재생 실패 — 스와이프해서 다음 영상으로',
            style: TextStyle(color: AppColors.sub)))
      else if (_c != null && _c!.value.isInitialized)
        FittedBox(fit: BoxFit.cover, clipBehavior: Clip.hardEdge,
            child: SizedBox(width: _c!.value.size.width,
                height: _c!.value.size.height, child: VideoPlayer(_c!)))
      else
        const Center(child: CircularProgressIndicator()),
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
    ]);
  }
}
