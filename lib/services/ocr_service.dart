import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;

/// 金额候选
class _MoneyCandidate {
  final double amount;
  final int position;
  final int priority; // 越高越优先

  _MoneyCandidate(this.amount, this.position, this.priority);
}

/// 百度 OCR 返回的识图结果
class OcrResult {
  final double? amount; // 识别出的金额
  final String? payee; // 识别出的收款方
  final String? productName; // 识别出的商品名称
  final String rawText; // 原始识别文字（用作备注）

  OcrResult({
    this.amount,
    this.payee,
    this.productName,
    required this.rawText,
  });

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
    // 候选金额：记录 (金额, 位置, 优先级)
    // 优先级：实付/实收=100, 合计/应付=90, 其他关键词=80, ￥符号=50, 纯数字=30
    final List<_MoneyCandidate> moneyCandidates = [];

    // 金额关键词
    final amountKeywords = RegExp(
        r'(?:金额|付款|实付|实收|应收|合计|合\s*计|总计|总\s*计|消费合计|消费|应付|支付|收款|找零)');

    // 高优先级关键词
    final highPriorityKw = RegExp(r'(?:实付|实收|应付)');
    final midPriorityKw = RegExp(r'(?:合计|合\s*计|总计|总\s*计)');

    for (int i = 0; i < words.length; i++) {
      final word = words[i];

      // 纯数字行：独占一行的 "-6.00"、"-5.00"
      final pureMatch = RegExp(r'^\s*(-?\d+\.\d{2})\s*$').firstMatch(word);
      if (pureMatch != null) {
        final val = double.tryParse(pureMatch.group(1)!);
        if (val != null) {
          final absVal = val.abs();
          if (absVal >= 1.0 && absVal < 1000000 && !looksLikeYear(absVal)) {
            moneyCandidates.add(_MoneyCandidate(absVal, i, 30));
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
          if (absVal >= 1.0 && absVal < 1000000 && !looksLikeYear(absVal)) {
            // 检查是否在同一个词中有关键词
            // 但如果词中包含"减"（折扣/优惠），说明这是优惠金额而非实付金额，
            // 不应被"实付"等关键词提升优先级
            final isDiscount = word.contains('减');
            int priority = 50;
            if (!isDiscount) {
              if (highPriorityKw.hasMatch(word)) priority = 100;
              else if (midPriorityKw.hasMatch(word)) priority = 90;
              else if (amountKeywords.hasMatch(word)) priority = 80;
            }
            moneyCandidates.add(_MoneyCandidate(absVal, i, priority));
          }
        }
      }

      // 35.50元
      final yuanMatch = RegExp(r'(-?\d+\.?\d{0,2})\s*元').firstMatch(word);
      if (yuanMatch != null) {
        final val = double.tryParse(yuanMatch.group(1)!);
        if (val != null) {
          final absVal = val.abs();
          if (absVal >= 1.0 && absVal < 1000000 && !looksLikeYear(absVal)) {
            final isDiscount = word.contains('减');
            int priority = 40;
            if (!isDiscount) {
              if (highPriorityKw.hasMatch(word)) priority = 100;
              else if (midPriorityKw.hasMatch(word)) priority = 90;
              else if (amountKeywords.hasMatch(word)) priority = 80;
            }
            moneyCandidates.add(_MoneyCandidate(absVal, i, priority));
          }
        }
      }

      // 金额:35.50、实付35.50、合计 128.00
      final keywordMatch = RegExp(
              r'(?:金额|付款|实付|实收|应收|合计|合\s*计|总计|总\s*计|消费合计|应付|消费|支付|收款|找零)[：:\s]*(-?\d+\.?\d{0,2})')
          .firstMatch(word);
      if (keywordMatch != null) {
        final val = double.tryParse(keywordMatch.group(1)!);
        if (val != null) {
          final absVal = val.abs();
          if (absVal >= 1.0 && absVal < 1000000 && !looksLikeYear(absVal)) {
            final isDiscount = word.contains('减');
            int priority = 80;
            if (!isDiscount) {
              if (highPriorityKw.hasMatch(word)) priority = 100;
              else if (midPriorityKw.hasMatch(word)) priority = 90;
            }
            moneyCandidates.add(_MoneyCandidate(absVal, i, priority));
          }
        }
      }

      // 相邻词匹配：关键词在一个词，数字在下一个词
      if (i + 1 < words.length && amountKeywords.hasMatch(word)) {
        final nextWord = words[i + 1].trim();
        // 去掉可能存在的 ¥ 符号再解析
        final nextClean = nextWord.replaceAll(RegExp(r'[¥￥]'), '').trim();
        final nextNum = double.tryParse(nextClean);
        if (nextNum != null && nextNum >= 1.0 && nextNum < 1000000) {
          int priority = 75;
          if (highPriorityKw.hasMatch(word)) priority = 100;
          else if (midPriorityKw.hasMatch(word)) priority = 90;
          moneyCandidates.add(_MoneyCandidate(nextNum, i + 1, priority));
        }
      }

      // 上一词是关键词，当前词是数字
      if (i > 0 && amountKeywords.hasMatch(words[i - 1])) {
        final numMatch = RegExp(r'^\s*(-?\d+\.?\d{0,2})\s*$').firstMatch(word);
        if (numMatch != null) {
          final val = double.tryParse(numMatch.group(1)!);
          if (val != null) {
            final absVal = val.abs();
            if (absVal >= 1.0 && absVal < 1000000 && !looksLikeYear(absVal)) {
              int priority = 75;
              if (highPriorityKw.hasMatch(words[i - 1])) priority = 100;
              else if (midPriorityKw.hasMatch(words[i - 1])) priority = 90;
              moneyCandidates.add(_MoneyCandidate(absVal, i, priority));
            }
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

    // 选最优金额：按优先级 → 离"支付成功"距离排序
    if (moneyCandidates.isNotEmpty) {
      // 去重（同一位置同一金额只保留优先级最高的）
      final seen = <int, _MoneyCandidate>{};
      for (final mc in moneyCandidates) {
        final key = mc.position;
        if (!seen.containsKey(key) || mc.priority > seen[key]!.priority) {
          seen[key] = mc;
        }
      }
      final deduped = seen.values.toList();

      // print('[OCR] 金额候选 (共${deduped.length}个):');

      deduped.sort((a, b) {
        // 先按优先级降序
        final pc = b.priority.compareTo(a.priority);
        if (pc != 0) return pc;
        // 同优先级：离"支付成功"越近越好
        if (paymentSuccessIndex >= 0) {
          return (a.position - paymentSuccessIndex).abs()
              .compareTo((b.position - paymentSuccessIndex).abs());
        }
        // 没有支付成功：位置靠前优先（金额通常在页面上方）
        return a.position.compareTo(b.position);
      });
      amount = deduped.first.amount;
    }

    // ---- 打印所有识别到的文字 ----
    // print('[OCR] 识别到 ${words.length} 行文字:');

    // ---- 2. 从文字中查找收款方 ----
    // 策略0：找"扫二维码付款-给XXX"或"向XXX付款"（微信扫码支付格式）
    for (final word in words) {
      final scanMatch = RegExp(r'扫二维码付款[-—]\s*给\s*(.+)').firstMatch(word);
      if (scanMatch != null) {
        var name = scanMatch.group(1)!.trim();
        name = name.replaceAll(RegExp(r'[，,。.\s\-]+$'), '');
        if (name.length >= 2 && name.length < 20 && hasChinese(name)) {
          payee = name;
          break;
        }
      }
      // 支付宝/银行格式："向XXX付款"
      final toMatch = RegExp(r'向\s*(.+?)\s*付款').firstMatch(word);
      if (toMatch != null) {
        var name = toMatch.group(1)!.trim();
        if (name.length >= 2 && name.length < 20 && hasChinese(name)) {
          payee = name;
          break;
        }
      }
    }

    // 策略1：找"收款方"/"商户"关键词，后面跟着的就是店名
    if (payee == null) {
      final payeeKeywords = [
        '收款商户', '商户简称', '收款店铺', '收款方', '商户',
      ];
      // "收款方XXX"中XXX不可能是这些词
      final notPayee = {'备注', '服务', '名片', '详情', '信息'};

      for (int i = 0; i < words.length; i++) {
        final word = words[i].trim();

        // 这些是UI标签，整体跳过
        if (word == '收款方备注' || word == '收款方服务' || word == '收款方名片' ||
            word == '商户全称' || word == '商户单号' || word == '收单机构') {
          continue;
        }

        for (final kw in payeeKeywords) {
          // 情况A：关键词在同一词内，后面紧跟店名
          if (word.startsWith(kw)) {
            var rest = word.substring(kw.length);
            rest = rest.replaceAll(RegExp(r'^[：:，,。.\s]+'), '');
            rest = rest.replaceAll(RegExp(r'[，,。.\s\-]+$'), '');
            if (rest.length >= 2 && rest.length < 30 &&
                hasChinese(rest) &&
                !notPayee.contains(rest)) {
              payee = rest;
              break;
            }
            // 同一词内无效，尝试下一个词
            if (rest.isEmpty && i + 1 < words.length) {
              var nextName = words[i + 1].trim();
              nextName = nextName.replaceAll(RegExp(r'[，,。.\s\-]+$'), '');
              if (nextName.length >= 2 && nextName.length < 30 &&
                  hasChinese(nextName) &&
                  !notPayee.contains(nextName)) {
                payee = nextName;
                break;
              }
            }
          }

          // 情况B：关键词独占一行，下一个词是店名
          final wordClean = word.replaceAll(RegExp(r'[：:，,。.\s]+$'), '');
          if (wordClean == kw && i + 1 < words.length) {
            for (int j = i + 1; j < words.length && j <= i + 2; j++) {
              var nextName = words[j].trim();
              nextName = nextName.replaceAll(RegExp(r'[，,。.\s\-]+$'), '');
              if (nextName.length >= 2 && nextName.length < 30 &&
                  hasChinese(nextName) &&
                  !notPayee.contains(nextName)) {
                payee = nextName;
                break;
              }
            }
            if (payee != null) break;
          }
        }
        if (payee != null) break;
      }
    }

    // 策略2：找"付款…给XXX"模式
    if (payee == null) {
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
    }

    // 策略3：扫描所有词，找最像店名的纯中文词
    if (payee == null) {
      String? bestName;
      double bestScore = 0;

      // 常见电商/支付UI文字，不可能是店名
      final notStoreName = {
        '交易成功', '交易关闭', '交易完成', '已签收', '已发货', '待发货', '待付款', '待收货',
        '申请售后', '加入购物车', '进店逛逛', '再买一单', '交易快照',
        '查看详情', '查看更多', '服务保障', '使用小贴士', '商品总价',
        '平台优惠', '店铺优惠', '店铺优惠官方立减', '官方立减', '退货宝', '极速退款',
        '展开', '复制', '客服', '更多', '共', '送至',
        '淘金币', '订单信息', '价保', '大促', '实付款', '共减',
        '旗舰店', '联系商家', '分享商品', '申请退款', '暑假大促',
        '预售', '品牌', '修改', '订单备注', '设为匿名', '再次拼单',
        '催发货', '先用后付', '免费送货上楼', '商家正在备货中',
        '消费提醒', '品牌认证', '官方旗舰', '百亿补贴', '秒杀',
        '收货人信息', '支付方式', '下单时间', '付款时间', '发货时间', '成交时间',
        '更多信息', '删除订单', '收起', '应用多种材质锅具',
        '快速除垢', '深层洁净', '器具养护', '必备',
      };

      for (int i = 0; i < words.length; i++) {
        var word = words[i].trim();
        // 去掉末尾常见的非文字符号（OCR常把">"粘在文字后面）
        word = word.replaceAll(RegExp(r'[.。>》」】›»)\]]+$'), '');
        if (word.isEmpty) continue;

        // 跳过明显不是店名的
        if (word.length < 2 ||
            word.length > 20 ||
            !hasChinese(word) || // 店名至少含一个中文
            word.contains('支付') ||
            word.contains('成功') ||
            word.contains('当前') ||
            word.contains('状态') ||
            word.contains('明细') ||
            word.contains('账单') ||
            word == '收款方' ||
            word == '收款商户' ||
            word == '商户简称' ||
            word == '商户' ||
            word == '收款店铺' ||
            word == '店铺' ||
            notStoreName.contains(word) ||
            RegExp(r'^\d+$').hasMatch(word) ||
            RegExp(r'^[¥￥]\s*\d').hasMatch(word) || // ¥48.71 这种
            RegExp(r'[-¥￥]\s*\d').hasMatch(word) || // -¥8.8 这种
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
        // 长度适中（3~12字最像店名）
        if (word.length >= 3 && word.length <= 12) {
          score += 2;
        }
        // 店名特征词加分（含"旗舰店""专营店""严选"等）
        // 位置越靠前，特征词权重越高（页面底部的推荐店铺不应抢走顶部真实店名）
        if (word.contains('旗舰店') ||
            word.contains('专营店') ||
            word.contains('专卖店')) {
          if (i <= 15) {
            score += 12; // 页面顶部，高度可信
          } else if (i <= 30) {
            score += 6;  // 页面中部，半可信
          } else {
            score += 2;  // 页面底部（推荐区），低可信
          }
        } else if (word.contains('严选') ||
                   word.contains('官方店') ||
                   word.contains('超市') ||
                   word.contains('商城')) {
          if (i <= 15) score += 8;
          else if (i <= 30) score += 4;
          else score += 1;
        }
        // 靠前位置加分（店名通常在页面顶部）
        if (i <= 10) {
          score += 5;
        } else if (i <= 20) {
          score += 2;
        } else if (i > 40) {
          score -= 2; // 页面很底部的位置，惩罚
        }
        // 靠近"交易成功"/"支付成功"加分
        if (paymentSuccessIndex >= 0 && (i - paymentSuccessIndex).abs() <= 5) {
          score += 1;
        }
        // 后面跟着"进店逛逛"（淘宝/天猫店名特征）
        if (i + 1 < words.length && words[i + 1].contains('进店逛逛')) {
          score += 8;
        }
        // 前面是"送至XXX"（外卖/快递场景，店名在收货地址后）
        if (i > 0 && words[i - 1].contains('送至')) {
          score += 4;
        }
        // 紧跟在"官方旗舰"之后（拼多多品牌区：品牌 → 官方旗舰 → 店名）
        // 前一个词必须短（≤8字），否则"官方旗舰"是店名的一部分，不是标签
        if (i > 0 && words[i - 1].contains('官方旗舰') && words[i - 1].length <= 8) {
          score += 12; // 高度可信：官方旗舰标签后面的就是品牌/店名
        } else if (i > 0 && words[i - 1].contains('品牌') && words[i - 1].length <= 6) {
          score += 3;  // "品牌"标签后面的可能是店名，但不如"官方旗舰"确定
        }
        // "【XXX】" 格式常见于拼多多店名
        if (word.startsWith('【') && word.contains('】')) {
          score += 6;
        }

        // 同分时保留先出现的词（店名通常在页面前部）
        if (bestName == null || score > bestScore) {
          bestScore = score;
          bestName = word;
        }
      }

      if (bestName != null) {
        payee = bestName;
      }
    }

    // ---- 3. 从文字中查找商品名称 ----
    String? productName;

    // 策略A：找 "×1,XXX" 格式（淘宝/拼多多商品标题常见格式）
    for (final word in words) {
      final match = RegExp(r'^[×xX]\s*1\s*[,，]\s*(.+)').firstMatch(word);
      if (match != null) {
        var name = match.group(1)!.trim();
        // 清理末尾标点
        name = name.replaceAll(RegExp(r'[>》」】›»)\]]+$'), '');
        name = name.replaceAll(RegExp(r'[【\[]+$'), '');
        if (name.length >= 3 && name.length < 80 && hasChinese(name)) {
          productName = name;
          break;
        }
      }
    }

    // 策略B：找最长的商品描述文字
    if (productName == null) {
      String? bestProduct;
      int bestLen = 0;

      // 已知的非商品文字
      final notProduct = {
        '交易成功', '交易关闭', '交易完成', '已签收', '已发货',
        '待发货', '待付款', '待收货', '申请售后', '加入购物车',
        '再买一单', '交易快照', '查看详情', '查看更多', '服务保障',
        '使用小贴士', '商品总价', '平台优惠', '店铺优惠', '官方立减',
        '退货宝', '极速退款', '展开', '复制', '客服', '更多',
        '联系商家', '分享商品', '申请退款', '暑假大促', '预售',
        '品牌', '修改', '订单备注', '设为匿名', '再次拼单', '催发货',
        '先用后付', '免费送货上楼', '商家正在备货中', '消费提醒',
        '品牌认证', '官方旗舰', '百亿补贴', '秒杀', '收货人信息',
        '支付方式', '下单时间', '付款时间', '发货时间', '成交时间',
        '更多信息', '删除订单', '订单编号', '订单号', '订单运费',
        '订单信息', '共优惠', '实付款', '实付', '共减', '收起',
        '降价补差', '商品快照', '拼单已同步到拼小圈',
      };

      // 确定搜索范围：店名之后、价格信息之前
      int searchStart = 3; // 跳过顶部状态栏
      int searchEnd = words.length;

      // 找到"实付"或"实付款"位置作为搜索终点
      for (int i = 0; i < words.length; i++) {
        if (words[i].contains('实付')) {
          searchEnd = i;
          break;
        }
      }

      for (int i = searchStart; i < searchEnd; i++) {
        var word = words[i].trim();
        word = word.replaceAll(RegExp(r'[.。>》」】›»)\]]+$'), '');

        // 跳过明显不是商品名的
        if (word.length < 5 ||
            word.length > 80 ||
            notProduct.contains(word) ||
            word == payee ||
            (payee != null && word.contains(payee)) ||
            RegExp(r'^\d+$').hasMatch(word) ||
            RegExp(r'^[¥￥]').hasMatch(word) ||
            word.contains('订单号') ||
            word.contains('复制') ||
            word.contains('支付') ||
            word.contains('退款') ||
            word.contains('物流') ||
            word.contains('快递') ||
            word.contains('送至') ||
            word.contains('收货') ||
            word.contains('收件人') ||
            word.contains('地址')) {
          continue;
        }

        // 商品名特征：较长的中文描述文字
        if (hasChinese(word)) {
          final dr = digitsRatio(word);
          // 数字占比过高（手机号等），不太可能是商品名
          if (dr > 0.4) continue;
          final chineseRatio = 1 - dr;
          // 中文占比高 + 字数多 = 更像商品描述
          final productScore = word.length * chineseRatio;

          if (productScore > bestLen) {
            bestLen = productScore.round();
            bestProduct = word;
          }
        }
      }

      if (bestProduct != null && bestProduct.length >= 4) {
        productName = bestProduct;
      }
    }

    return OcrResult(
      amount: amount,
      payee: payee,
      productName: productName,
      rawText: rawText,
    );
  }
}

/// 百度 OCR 云服务
class BaiduOcrService {
  static const _tokenUrl = 'https://aip.baidubce.com/oauth/2.0/token';
  static const _ocrUrl =
      'https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic';

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
