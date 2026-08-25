/// 경고 배너 표시 규칙.
/// - 노출 80% 이상 + 필터 OFF 일 때만
/// - 사용자가 닫았다면(dismissedAt = 닫을 당시 %) 그보다 10%p 이상 더
///   올라가기 전까지는 다시 띄우지 않는다.
bool shouldShowBanner({required double? percent, required bool filterOn,
    double? dismissedAt}) {
  if (percent == null || percent < 80 || filterOn) return false;
  if (dismissedAt != null && percent < dismissedAt + 10) return false;
  return true;
}
