import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/models.dart';
import '../state/feed.dart';
import '../theme.dart';

class ActionRail extends ConsumerWidget {
  final FeedVideo video;
  const ActionRail({super.key, required this.video});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    void dummy() => ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('준비 중입니다')));
    Widget item(IconData ic, String label, VoidCallback onTap,
            {Color? color}) =>
        Padding(padding: const EdgeInsets.only(bottom: 14), child: Column(
          children: [
            InkWell(onTap: onTap, customBorder: const CircleBorder(),
                child: Container(width: 46, height: 46,
                    decoration: BoxDecoration(shape: BoxShape.circle,
                        color: Colors.white.withValues(alpha: .12),
                        border: Border.all(
                            color: Colors.white.withValues(alpha: .18))),
                    child: Icon(ic, size: 21, color: color ?? Colors.white))),
            const SizedBox(height: 5),
            Text(label, style: TextStyle(fontSize: 11,
                color: Colors.white.withValues(alpha: .9))),
          ]));
    return Column(mainAxisSize: MainAxisSize.min, children: [
      item(video.likedByMe ? Icons.favorite : Icons.favorite_border,
          '${video.likeCount}',
          () => ref.read(feedProvider.notifier).toggleLike(video.id),
          color: video.likedByMe ? AppColors.red : null),
      item(Icons.mode_comment_outlined, '댓글', dummy),
      item(Icons.share_outlined, '공유', dummy),
      item(Icons.autorenew, '리믹스', dummy),
    ]);
  }
}
