import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;

/// 百度 OCR 返回的识图结果
class OcrResult {
  final double? amount; // 识别出的金额
  final String? payee; // 识别出的收款方
  final String rawText; // 原始识别文字（用作备注）

  OcrResult({this.amount, this.payee, required this.rawText});

  /// 从百度返回的文字列表解析出金额和收款方
  factory OcrResult.parse(List<String> words) {
    final rawText = words.join('\n');
    double? amount;
    String? payee;

    // ---- 辅助函数 ----
    bool looksLikeYear(double val) =>
        val >= 1900 && val <= 2099 && val == val.roundToDouble();

    bool hasChinese(String s) => RegExp(r'[一-鿿]').hasMatch(s);
    bool isPureChinese(String s) =>
        RegExp(r'^[一-鿿·]+$').hasMatch(s.trim());
    double digitsRatio(String s) {
      final digits = RegExp(r'\d').allMatches(s).length;
      final letters = RegExp(r'[a-zA-Z]').allMatches(s).length;
      final total = s.trim().length;
      return total > 0 ? (digits + letters) / total : 0;
    }

    // ---- 1. 从文字中查找金额 ----
    // 候选金额：记录 (金额, 在words中的位置)
    final List<MapEntry<double, int>> moneyCandidates = [];

    for (int i = 0; i < words.length; i++) {
      final word = words[i];

      // 纯数字行：独占一行的 "-6.00"、"-5.00"
      final pureMatch = RegExp(r'^\s*(-?\d+\.\d{2})\s*$').firstMatch(word);
      if (pureMatch != null) {
        final val = double.tryParse(pureMatch.group(1)!);
        if (val != null) {
          final absVal = val.abs();
          if (absVal > 0 && absVal < 1000000 && !looksLikeYear(absVal)) {
            moneyCandidates.add(MapEntry(absVal, i));
          }
        }
      }

      // ¥5.00、￥6.00
      final symbolMatch =
          RegExp(r'[¥￥]\s*(-?\d+\.?\d{0,2})').firstMatch(word);
      if (symbolMatch != null) {
        final val = double.tryParse(symbolMatch.group(1)!);
        if (val != null) {
          final absVal = val.abs();
          if (absVal > 0 && absVal < 1000000 && !looksLikeYear(absVal)) {
            moneyCandidates.add(MapEntry(absVal, i));
          }
        }
      }

      // 35.50元
      final yuanMatch = RegExp(r'(-?\d+\.?\d{0,2})\s*元').firstMatch(word);
      if (yuanMatch != null) {
        final val = double.tryParse(yuanMatch.group(1)!);
        if (val != null) {
          final absVal = val.abs();
          if (absVal > 0 && absVal < 1000000 && !looksLikeYear(absVal)) {
            moneyCandidates.add(MapEntry(absVal, i));
          }
        }
      }

      // 金额:35.50、实付35.50
      final keywordMatch = RegExp(
              r'(?:金额|付款|实付|合计|总计|消费|支付|收款)[：:]\s*(-?\d+\.?\d{0,2})')
          .firstMatch(word);
      if (keywordMatch != null) {
        final val = double.tryParse(keywordMatch.group(1)!);
        if (val != null) {
          final absVal = val.abs();
          if (absVal > 0 && absVal < 1000000 && !looksLikeYear(absVal)) {
            moneyCandidates.add(MapEntry(absVal, i));
          }
        }
      }
    }

    // 找"支付成功"的位置（金额和收款方逻辑共用）
    int paymentSuccessIndex = -1;
    for (int i = 0; i < words.length; i++) {
      if (words[i].contains('支付成功') ||
          words[i].contains('支付') ||
          words[i].contains('成功')) {
        paymentSuccessIndex = i;
        break;
      }
    }

    // 选最优金额：离"支付成功"最近的候选
    if (moneyCandidates.isNotEmpty) {

      if (paymentSuccessIndex >= 0) {
        // 找离"支付成功"最近的金额
        moneyCandidates.sort((a, b) =>
            (a.value - paymentSuccessIndex).abs()
                .compareTo((b.value - paymentSuccessIndex).abs()));
      } else {
        // 没有"支付成功"，取最后一个（通常在图片下方）
        moneyCandidates.sort((a, b) => b.value.compareTo(a.value));
      }
      amount = moneyCandidates.first.key;
    }

    // ---- 2. 从文字中查找收款方 ----
    // 策略1：找"付款…给XXX"模式
    for (final word in words) {
      final match = RegExp(r'付款.*?给\s*(.+)').firstMatch(word);
      if (match != null) {
        var name = match.group(1)!.trim();
        name = name.replaceAll(RegExp(r'[，,。.\s\-]+$'), '');
        if (name.isNotEmpty && name.length < 30) {
          payee = name;
          break;
        }
      }
    }

    // 策略2：扫描所有词，找最像店名的纯中文词
    if (payee == null) {
      String? bestName;
      double bestScore = 0;

      for (int i = 0; i < words.length; i++) {
        final word = words[i].trim();

        // 跳过明显不是店名的
        if (word.length < 2 ||
            word.length > 20 ||
            word.contains('支付') ||
            word.contains('成功') ||
            word.contains('当前') ||
            word.contains('状态') ||
            word.contains('明细') ||
            word.contains('账单') ||
            RegExp(r'^\d+$').hasMatch(word) ||
            word == '+' ||
            word == '-' ||
            word == '其他') {
          continue;
        }

        double score = 0;

        // 纯中文加分
        if (isPureChinese(word)) {
          score += 5;
        }
        // 含中文加分
        if (hasChinese(word)) {
          score += 2;
        }
        // 数字字母比例越低越好（店名不应有太多数字）
        final dr = digitsRatio(word);
        score += (1 - dr) * 3;
        // 长度适中（2~8字最像店名）
        if (word.length >= 3 && word.length <= 8) {
          score += 2;
        }
        // 靠近"支付成功"/金额位置加分（店名通常在金额附近）
        if (paymentSuccessIndex >= 0 && (i - paymentSuccessIndex).abs() <= 5) {
          score += 1;
        }

        if (score > bestScore) {
          bestScore = score;
          bestName = word;
        }
      }

      if (bestName != null) {
        payee = bestName;
      }
    }

    return OcrResult(amount: amount, payee: payee, rawText: rawText);
  }
}

/// 百度 OCR 云服务
class BaiduOcrService {
  static const _tokenUrl = 'https://aip.baidubce.com/oauth/2.0/token';
  static const _ocrUrl =
      'https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic';

  final String apiKey;
  final String secretKey;

  String? _accessToken;
  DateTime? _tokenExpiry;

  BaiduOcrService({required this.apiKey, required this.secretKey});

  /// 获取百度 API 访问令牌（带缓存，30天有效期）
  Future<String> _getAccessToken() async {
    if (_accessToken != null &&
        _tokenExpiry != null &&
        DateTime.now().isBefore(_tokenExpiry!)) {
      return _accessToken!;
    }

    final response = await http.post(
      Uri.parse(_tokenUrl),
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body:
          'grant_type=client_credentials&client_id=$apiKey&client_secret=$secretKey',
    );

    if (response.statusCode == 200) {
      final json = jsonDecode(response.body);
      _accessToken = json['access_token'] as String;
      // 有效期 30 天，缓存 29 天
      _tokenExpiry = DateTime.now().add(const Duration(days: 29));
      return _accessToken!;
    }

    throw Exception('获取百度OCR令牌失败，请检查API Key是否正确');
  }

  /// 识别图片中的文字，返回解析后的结果
  Future<OcrResult> recognizeImage(File imageFile) async {
    final token = await _getAccessToken();

    // 读取图片并转为 base64
    final bytes = await imageFile.readAsBytes();
    final base64Image = base64Encode(bytes);

    // 调用百度通用文字识别 API
    final response = await http.post(
      Uri.parse('$_ocrUrl?access_token=$token'),
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'image=${Uri.encodeComponent(base64Image)}',
    );

    if (response.statusCode == 200) {
      final json = jsonDecode(response.body);
      final errorCode = json['error_code'];
      if (errorCode != null) {
        throw Exception('OCR识别失败: ${json['error_msg'] ?? '未知错误'}');
      }
      final wordsList = (json['words_result'] as List?)
              ?.map((w) => w['words'] as String)
              .toList() ??
          [];
      if (wordsList.isEmpty) {
        throw Exception('图片中未识别到文字，请确保图片清晰且包含文字');
      }
      return OcrResult.parse(wordsList);
    }

    throw Exception('请求百度OCR失败，请检查网络连接');
  }
}
