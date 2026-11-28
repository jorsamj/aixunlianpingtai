# U3-P3-A 澧為噺鍚屾鍓嶇疆鍑嗗锛?026-11-28锛?

> 鏈枃鍙褰?*鐜版湁浠ｇ爜瀵瑰簲鐨勪簨瀹?*涓?P3-B 鐨勬渶灏忓疄鏂藉悎鍚岋紱鏈疆涓嶆柊澧?Change Log Schema銆?
> 涓嶅啓鍚屾 Worker銆佷笉寤洪槦鍒?瀹氭椂浠诲姟/娓呯悊浠诲姟銆佷笉鍚敤鐢熶骇寮€鍏炽€佷笉鏀?VERSION銆?

## 1. Owner 鍐欏叆鍏ュ彛锛堝奖鍝?Picker 鎶曞奖鐨勮矾寰勶級

### Material 鈥?`platform_core/material_repository.py`

| 鍏ュ彛 | 浜嬪姟 | 鐗堟湰鏁堟灉 | 骞傜瓑/鍥存爮 |
|---|---|---|---|
| `upsert` / `upsert_many` | 鍗?SQLite 鍐欎簨鍔?| `material_meta.revision` +1锛涘唴瀹瑰彉鍖栨椂 `evidence_generation` +1锛堣Е鍙戯級 | 涓婚敭 + `INSERT OR REPLACE`锛沗material_annotation_lifecycle_fence` 澶栧眰鐨勫鍑?GT 鍐欏叆 |
| 鍒犻櫎/閫€褰癸紙鍒犻櫎 claim銆乣material_retirements`锛?| 鍗曞啓浜嬪姟 | revision +1锛沗evidence_generation` +1锛堣Е鍙戯級 | `_dataset_delete_claim`/`_material_batch_delete_claim`銆乺etirement 璁板綍 |
| 鏍囩/鏍囨敞鑼冨洿锛坄material_labels`銆乣material_annotation_scopes`锛?| 鍗曞啓浜嬪姟 | revision +1 | 涓婚敭瑕嗙洊 |
| 瀛樺偍婧愬彉鍖栵紙`material_storage_audit`/瀛楁鏇存柊锛?| 鍗曞啓浜嬪姟 | revision +1锛涘璁¤鎻掑叆 bump evidence | 瀹¤ `id` 鍞竴 |
| 璇佹嵁鍐欏叆锛坄material_migrations`/`material_storage_audit`/`material_retirements`/`material_cleanup_deferred`/`material_assignment_receipts`/`negative_pool_operations`锛?| 涓庝笟鍔″啓鍚屼簨鍔?| `evidence_generation` +1锛堟瘡琛ㄨЕ鍙戝櫒锛?| 鍚勮嚜涓婚敭/鎿嶄綔閿?|

### Annotation 鈥?`platform_core/annotation_repository.py`

| 鍏ュ彛 | 浜嬪姟 | 鐗堟湰鏁堟灉 | 骞傜瓑/鍥存爮 |
|---|---|---|---|
| `save_annotation`锛圙T 鏂板/鏇存柊/瑕嗙洊锛?| `BEGIN IMMEDIATE` + `material_annotation_lifecycle_fence` | `annotation_meta.revision` +1锛涜瘉鎹?generation锛坄annotation_delete_backup` 绛夛級瑙﹀彂 | 鐗堟湰 CAS锛堣皟鐢ㄦ柟鏍￠獙 `version`锛夛紱寮曠敤琛ㄩ噸寤?|
| GT 鍒犻櫎/鍥炴粴锛坄annotation_delete_backup`锛?| 鍚屼簨鍔?| revision +1锛涜瘉鎹?generation +1 | 澶囦唤琛?|
| 鏍囨敞鑼冨洿鍙樺寲 | 闅?GT 鍐欏叆 | revision +1 | 鈥?|
| `commit_candidate_decisions` / candidate commit | 鍗曞啓浜嬪姟 | revision +1锛沗annotation_candidate_commits` 瑙﹀彂 | 鍊欓€?ID 骞傜瓑 |
| negative review | 鍗曞啓浜嬪姟 | revision +1锛沗negative_reviews` 瑙﹀彂 | 瀹℃牳閿?|
| `confirm_task_negatives` | `material_annotation_lifecycle_fence` + `BEGIN IMMEDIATE` | `task_negative_confirmations` 琛岋紱`task_negative_confirmation_generation` +1锛堣Е鍙戝櫒锛夛紱璇佹嵁 generation +1 | `receipt_id` 涓婚敭 + `INSERT OR IGNORE`锛堝箓绛夛級 |

### Negative Pool 鈥?`platform_core/negative_pool.py`

| 鍏ュ彛 | 浜嬪姟 | 鐗堟湰鏁堟灉 | 骞傜瓑/鍥存爮 |
|---|---|---|---|
| `members` / `categories` / `links` / `algorithm_scope` 鍙樻洿 | 鍗曞啓浜嬪姟锛坄_mutate`锛?| `negative_pool_meta.revision` +1锛沗negative_pool_operations` 瑙﹀彂 evidence generation | `operation_id` + `operation_kind` + 鍘熷 `expected_revision` 骞傜瓑閲嶆斁 |

**鍏辨€?*锛氭墍鏈夊叆鍙ｉ兘鍦ㄥ悇鑷?SQLite 鏂囦欢鐨勫崟浜嬪姟鍐呭畬鎴愪笟鍔″啓 + 鐗堟湰/璇佹嵁瑙﹀彂鏇存柊锛涙病鏈夎法搴撳弻鍐欙紱
瀵煎嚭/瀵煎叆棰濆鎸佹湁 `material_annotation_lifecycle_fence` 闃叉瀵煎嚭鏈熼棿鍐欏叆銆傜粫杩囩粺涓€鍏ュ彛鐩存帴
`sqlite3` 鍐欐枃浠朵笉灞炰簬鍙楁敮鎸佽矾寰勶紙P0 瀵煎叆浼氫互 revision/digest/structure 闂ㄧ鎷掔粷锛夈€?

## 2. Change Log 鍚堝悓锛圥3-B 瀹炴柦绾︽潫锛?

1. 姣忎釜 Owner 鏂囦欢鏂板 `owner_change_log(stream, sequence, event_kind, entity, tombstone_json, payload_digest, schema_version)`锛?
   涓庝笟鍔″啓**鍚屼竴 SQLite 浜嬪姟**鎻愪氦锛屼笟鍔″洖婊氬垯鏃ュ織鍥炴粴銆?
2. `stream` = `materials` / `annotations` / `negative_pool`锛沗sequence` 姣忔祦鍗曡皟閫掑锛?
   鐢辨祦鍐?`meta.change_sequence` 鍦ㄤ簨鍔″唴鑷锛屼笉渚濊禆姣鏃堕棿鎴炽€?
3. `event_kind` 鈭?`insert|update|delete`锛堟垨绛変环锛夛紱delete 蹇呴』鍐?tombstone锛堜富閿?+ 鍒犻櫎鍘熷洜 +
   鍘?revision/generation锛夛紝渚?PG 鍒犻櫎涓庡箓绛夐噸鏀俱€?
4. 姣忔潯浜嬩欢鎼哄甫 `payload_digest`锛堣瀹炰綋鎶曞奖鍐呭鐨勮鑼冨寲鎽樿锛変笌 `schema_version`锛?
   閲嶆斁鏃跺悓 `(stream, sequence)` 涓旀憳瑕佺浉鍚屽嵆骞傜瓑璺宠繃锛屾憳瑕佷笉鍚屽嵆 `DIVERGED` 鎷掔粷鎺ㄨ繘銆?
5. 澶?Owner 涔嬮棿**鏃犲叏灞€椤哄簭**锛汸G 娑堣垂鎸夋祦鐙珛鎺ㄨ繘锛宍u3_projection_cursor` 澶嶇敤鐜版湁琛紝
   姣忎釜娴佷竴涓父鏍囷紝浜嬪姟鍐呪€滃簲鐢ㄤ簨浠?+ 鎺ㄨ繘娓告爣鈥濅竴璧锋彁浜わ紙涓嶆帹杩涙湭瀹屾垚鏁版嵁锛夈€?
6. `revision_vector`/`picker_snapshot_state` 缁х画鐢辩幇鏈?P0 瀵煎叆浜х敓锛屼笉閲嶉€狅紱澧為噺娑堣垂瀹屾垚涓€鎵瑰悗
   鐢卞鍏ヨ矾寰勬洿鏂?revision/generation 涓庣姸鎬併€?

## 3. 鍒濆鍖栦笌澧為噺琛旀帴

1. 鍒濆瀹屾暣蹇収锛氱幇鏈?`export_project_snapshot` / `import_project_snapshot`锛圧EADY锛夈€?
2. 瀵煎嚭寮€濮嬫椂璁板綍鍚勬祦 high-water mark锛坄change_sequence`锛夛紝瀵煎嚭鏈熼棿鏂板啓鍏ヤ細杩涘叆鏃ュ織銆?
3. 蹇収鍙戝竷鍚庯紝澧為噺浠?high-water mark+1 寮€濮嬫秷璐癸紱鑻ユ煇娴佸皻鏃犳棩蹇楋紙鑰侀」鐩級锛屽厛鎵ц涓€娆?
   鈥滃熀绾夸簨浠垛€濓紙鎶婂綋鍓嶆姇褰辫涓?insert锛夛紝鎴栫洿鎺ヤ互瀹屾暣閲嶅缓寤虹珛鍩虹嚎銆?
4. 鑰侀」鐩病鏈夊巻鍙蹭簨浠讹細鍏佽 `u3_projection_cursor` 浠庡熀绾夸綅缃捣姝ワ紱绂佹鎶娾€滄棤鏃ュ織鈥濆綋浣?
   鈥滄棤鏁版嵁鈥濄€?
5. 閲嶅娑堣垂锛氬箓绛夐敭 `(stream, sequence)`锛涙父鏍囧彧鍦ㄤ簨鍔℃垚鍔熷悗鎺ㄨ繘銆?
6. 缂哄彛/鏃犳硶鎭㈠锛歚sequence` 涓嶈繛缁垨鎽樿涓嶄竴鑷?鈫?鍋滄澧為噺锛岃蛋鍙楁帶瀹屾暣蹇収閲嶅缓锛?
   涓嶅厑璁告竻绌烘暣涓?PG 鎶曞奖鏉ユ帺鐩栧紓甯革紙P0 鏃у揩鐓?璇佹嵁淇濈暀鍚堝悓缁х画鏈夋晥锛夈€?
7. 涓柇锛歐orker 宕╂簝鏃?PG 浜嬪姟鍥炴粴锛屾父鏍囦笉鍓嶈繘锛汼QLite 鏃ュ織淇濈暀锛岄噸鍚悗閲嶆斁銆?
8. 澶辫触鎭㈠锛歋QLite Owner 涓嶅彲鐢?鈫?鏆傚仠锛汸G 涓嶅彲鐢?鈫?閲嶈瘯鏈夌晫鍚庢殏鍋滐紱涓よ€呴兘涓嶄慨鏀?Owner 鏁版嵁銆?
9. 鏃ュ織淇濈暀锛歅3-B 鍙拷鍔狅紱娓呯悊闇€瑕佺嫭绔嬫巿鏉冿紙淇濈暀绐楀彛 鈮?鏈€闀垮揩鐓ч噸寤哄懆鏈燂級銆?

## 4. 鏈€灏忓疄鏂借寖鍥达紙P3-B 寤鸿锛?

1. 涓変釜 Owner 鐨?`owner_change_log` DDL + 浜嬪姟鍐呰拷鍔犲嚱鏁帮紙鍚勪竴涓紝澶嶇敤鐜版湁 `_mutate`/鍐欎簨鍔★級銆?
2. 姣忔祦 `change_sequence` 涓?high-water mark 璇诲彇 API锛堝彧璇伙級銆?
3. 涓€涓棤 Worker 鐨?`apply_change_batch(connection, stream, events)` 绾嚱鏁?+ 鍗曟祴銆?
4. `u3_projection_cursor` 澶嶇敤涓庘€滃簲鐢?鎺ㄨ繘鍚屼簨鍔♀€濆皝瑁呫€?
5. 瀹屾暣閲嶅缓鍏ュ彛澶嶇敤鐜版湁瀵煎叆锛涚己鍙ｆ娴?鈫?閲嶅缓鏍囧織銆?
6. 鏆備笉鍋氾細娑堟伅闃熷垪銆佸畾鏃跺櫒銆佽嚜鍔ㄦ竻鐞嗐€佺敓浜у紑鍏炽€佽法搴撳弻鍐欍€?

## 5. 鏄庣‘鏈仛

P3-A 鏈韩鏈柊澧?Schema/琛ㄣ€佹湭瀹炵幇 Worker/闃熷垪/瀹氭椂鍚屾銆佹湭鏀?Owner 鍐欏叆璺緞銆佹湭鏀?
VERSION銆侾3-B1/B2 鐨勫疄鏂借绗?8/9 鑺傦紱B3/B4 浠嶆湭瀹炵幇锛岀敓浜?Picker 璇诲彇鏈惎鐢ㄣ€?

## 6. 瀹¤琛ュ厖鍚堝悓

1. **浜嬩欢 payload 涓庢憳瑕?*锛氫簨浠跺彧鍐欏疄浣撲富閿€乣event_kind`銆乣tombstone_json`锛坉elete锛変笌
   `payload_digest`锛涘畬鏁村疄浣撳唴瀹逛粛浠?Owner 琛屼负鍑嗐€傛秷璐硅€呮寜 `payload_digest` 骞傜瓑姣斿锛屽疄浣撳悗缁?
   鍙樺寲浜х敓鏂扮殑 `(stream, sequence)`锛屼笉澶嶇敤鏃ф憳瑕併€?
2. **鍩虹嚎涓?high-water mark 鍚屽揩鐓?*锛氬垵濮嬪寲蹇収蹇呴』鍦?*鍚屼竴 SQLite 鍙浜嬪姟**鍐呰鍙栧悇娴?
   `change_sequence`锛屽鍑烘暟鎹篃鏉ヨ嚜璇ヤ簨鍔★紱鍙戝竷 READY 鍚庡閲忎粠 `hwm+1` 寮€濮嬫秷璐癸紝閬垮厤鈥滃鍑烘湡闂?
   鍐欏叆涓㈠け鈥濄€?
3. **璺ㄦ祦渚濊禆涓?READY**锛歚picker_snapshot_state.status=READY` 浠嶇敱瀹屾暣瀵煎叆浜х敓锛涘閲忔秷璐逛笉寰楀湪
   娴佹湭瀵归綈锛堝 GT 鍏堜簬鍏剁礌鏉愩€佺‘璁ゅ厛浜庡叾 GT锛夋椂鎺ㄨ繘鍏ㄥ眬 READY锛屾寜娴佺嫭绔嬫父鏍?+ 渚濊禆妫€鏌ワ紝
   浠讳竴渚濊禆缂哄け鍗虫殏鍋滃苟淇濈暀鏃?READY 蹇収銆?
4. **骞傜瓑/缂哄彛/澶辫触/閲嶅缓**锛歚(stream, sequence)` + 鎽樿骞傜瓑锛涘簭缂哄彛銆佹憳瑕佷笉涓€鑷存垨 Owner 缁撴瀯
   鏈璇?鈫?鍋滄澧為噺銆佹爣璁伴噸寤猴紱閲嶅缓澶嶇敤鐜版湁瀹屾暣瀵煎嚭/瀵煎叆锛屼笉娓呯┖ PG 鎶曞奖鎺╃洊寮傚父锛汷wner 鏁版嵁
   姘镐笉鍥犲悓姝ュけ璐ヨ淇敼銆?

## 7. 浜嬩欢鍐呭涓?READY 鍘熷瓙鍙戝竷锛堟渶缁堟敹鍙ｏ級

1. **涓嶅彲鍙樻姇褰变簨浠?*锛氫簨浠跺繀椤绘惡甯﹁瀹炰綋鐨?*瀹屾暣鎶曞奖蹇収**锛坢aterial/GT/pool 琛岀殑瑙勮寖鍖?
   瀛楁 + `payload_digest`锛夛紝鑰屼笉鏄彧甯︿富閿垨鈥滄棫鎽樿鈥濄€傛秷璐硅€呮寜 `(stream, sequence)` 鍐欏叆
   浜嬩欢鎵€鎻忚堪鐨勯偅涓€鐗堝疄浣擄紱瀹炰綋鍚庣画鍙樺寲浼氫骇鐢熸洿楂?sequence 鐨勬柊浜嬩欢锛岀姝㈢敤鏃ф憳瑕佸幓璇诲彇宸?
   鍙樺寲鐨勫疄浣撱€傝嫢浜嬩欢鍙甫鍙樻洿閿紝蹇呴』鍚屾椂璇佹槑鍙悎骞剁殑楂樻按浣嶏紙`sequence` + 瀹炰綋
   `updated_generation`锛夛紝涓斿悎骞剁粨鏋滀笌鐩存帴璇?Owner 涓€鑷淬€?
2. **澧為噺鏈熼棿鐨勫彲瑙佹€?*锛氭秷璐规壒娆″湪 PG 浜嬪姟鍐呭簲鐢ㄤ簨浠跺苟鎺ㄨ繘璇ユ祦娓告爣锛涙壒娆℃彁浜ゅ墠
   `picker_snapshot_state.status=STALE`锛堟垨淇濈暀鏃?READY 浣嗕笉寰楁敼鍙樺叾 `snapshot_id` 鎸囧悜鐨勫唴瀹癸級銆?
   鍙湁鎵€鏈夋祦娓告爣涓?`revision_vector` 瀵归綈銆佷緷璧栨鏌ラ€氳繃鍚庯紝鎵嶅湪鍚屼竴浜嬪姟鍐呭彂甯冩柊鐨?READY
   韬唤锛涚姝⑩€滄棫 READY 韬唤鎸囧悜宸插彉鍖栫殑鎶曞奖鈥濄€?
3. 淇濇寔锛氭瘡 Owner 鍚屼簨鍔℃棩蹇椼€佸崟璋?sequence銆乼ombstone銆佸箓绛夐噸鏀俱€佺己鍙ｆ娴嬩笌瀹屾暣閲嶅缓锛?
   澧為噺澶辫触涓嶆敼 Owner锛屼笉鐢ㄦ竻绌烘姇褰辨帺鐩栧紓甯搞€?

## 8. P3-B1 宸插疄鏂斤紙`platform_core/u3_owner_change_log.py`锛?

1. 姣忎釜 Owner 鏁版嵁搴撴柊澧?`owner_change_log` / `owner_change_meta`锛沗materials.sqlite3`
   鎵胯浇 `materials` 涓?`negative_pool` 涓や釜鐙珛 sequence锛宍annotations.sqlite3` 鎵胯浇
   `annotations`銆備簨浠惰〃涓?append-only锛圲PDATE/DELETE 瑙﹀彂鍣ㄦ嫆缁濓級銆?
2. `append_events` 鍦ㄨ皟鐢ㄦ柟鐜版湁 `BEGIN IMMEDIATE` 浜嬪姟鍐呭垎閰嶈繛缁?sequence銆佽绠楀苟鎸佷箙鍖?
   `payload_digest`锛涗笟鍔″洖婊氭椂鏃ュ織涓?sequence 涓€璧峰洖婊氾紝澶辫触鍏抽棴銆?
3. 浜嬩欢 payload 鏄啓鍏ヤ簨鍔″唴鐢熸垚鐨勫畬鏁存姇褰卞揩鐓э細material 鍚瀛楁銆乸ayload銆乴abels銆?
   annotation_scope锛沘nnotation 鍚?boxes/scope 涓?`annotation_label_references`锛?
   negative pool 鍚?member/links/algorithms 鎴?category锛涚‘璁ゅ洖鎵т笌鍘嗗彶璇佹嵁浜嬩欢鐙珛鎼哄甫
   鍘熻〃琛屽唴瀹广€傚垹闄?閫€褰?绉婚櫎鍐?tombstone锛屽悗缁疄浣撳彉鍖栦笉浼氶噸鍐欐棫浜嬩欢銆?
4. 瀹為檯鍐欏叆鍏ュ彛锛歚MaterialRepository._write_row` / `remove` / `retire_many` /
   `reconcile_storage_batch` / `record_*` / assignment receipts銆乥atch 妯″潡鐨?
   `_persist_batch` 涓庢壒閲?remove/mutate銆乣NegativePool._mutate`锛坢embers/category/
   restore锛夊強 `AnnotationRepository.upsert_many` / `confirm_task_negatives` /
   delete/restore/remove銆傛棫搴撶敱 `_initialize` 骞傜瓑琛ュ缓锛孭0 璇佹嵁缁撴瀯璁よ瘉涓嶅彉銆?
5. 鏄庣‘鏈仛锛氭病鏈?Worker銆侀槦鍒椼€佸畾鏃跺櫒銆佽嚜鍔ㄦ竻鐞嗐€佺敓浜у紑鍏筹紱鏈惎鐢ㄦ寮?Picker 璇诲彇銆?

## 9. P3-B2 宸插疄鏂斤紙`platform_core/u3_incremental_sync.py`锛?

1. `apply_incremental_batch(connection, project_dir=..., project_id=..., stream=...,
   limit=...)` 鎸夋祦璇诲彇 `sequence > cursor` 鐨勬湁鐣屼簨浠讹紝鏍￠獙 project/stream/schema/
   digest 涓庤繛缁€с€?
2. 涓€涓?PostgreSQL 浜嬪姟鍐咃細灏嗘棦鏈?READY 鏍囪涓?STALE銆佸簲鐢?material/annotation/
   confirmation/negative-pool/evidence 浜嬩欢銆佸啓 `u3_applied_owner_event`銆佹帹杩?
   `u3_projection_cursor`銆備换涓€姝ュけ璐ユ暣鎵瑰洖婊氾紝SQLite Owner 涓嶈鍙嶅悜淇敼銆?
3. 宸插鐞嗗箓绛夐噸鏀撅紙鍚?sequence 鍚?digest 璺宠繃锛夈€佸悓韬唤鎽樿鍐茬獊鎷掔粷銆乻equence 缂哄彛鎷掔粷銆?
   鏃?annotation 浜嬩欢涓嶈鐩栨洿楂?version銆佸垹闄?tombstone 涓庨」鐩殧绂汇€?
4. 鏂板 B2-only 琛?`u3_applied_owner_event` 浠呬繚瀛樻秷璐规憳瑕佸嚟鎹紱鏈敼鍘嗗彶杩佺Щ/P0 琛ㄣ€?
5. 鏄庣‘鏈仛锛欱3 鐨勫熀绾?high-water mark 琛旀帴銆佽法娴?READY 鍘熷瓙鍙戝竷銆乺evision_vector 瀵归綈锛?
   B4 鐨勪腑鏂仮澶?瀹屾暣閲嶅缓銆傚綋鍓嶅閲忓悗椤圭洰淇濇寔 STALE锛屼笉鑳戒綔涓烘寮?READY 璇诲彇銆?
