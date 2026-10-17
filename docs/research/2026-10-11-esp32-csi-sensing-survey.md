# ESP32 / commodity WiFi CSI sensing: literature survey

Date: 2026-10-11. Scope: multistatic ESP32-S3 CSI (3 nodes, 6 directional links, 2.4 GHz, 1x1) with a cheap mmWave radar (HLK-LD2410 / LD6002) used as a continuous teacher, plus camera pose labels during collection. Covers presence, zones, counting, coarse posture, breathing, and adapting to new rooms.

Conventions: numbers are quoted as the source reports them, along with the hardware and the evaluation split. "Not verified" means I could not open the primary full text, and the claim comes from an abstract or search snippet only. "Inference" marks my own reasoning, which no source states.

---

## Summary (key takeaways)

1. **WiFi works well in the room it was trained in and falls apart in a new one.** The cleanest controlled comparison is MM-Fi, where WiFi and mmWave were recorded on the same subjects. For 3D pose, WiFi MPJPE goes from 186.9 mm (random split) to 367.8 mm (cross-environment). mmWave goes from 109.8 mm to 166.2 mm ([MM-Fi](https://arxiv.org/abs/2305.10345), Table 3, Protocol 1). DensePose-from-WiFi drops from AP 43.5 (same layout) to 27.3 (unseen layout) ([Geng et al.](https://arxiv.org/abs/2301.00250)). This gap is the core argument for a radar teacher.
2. **mmWave is less sensitive to the environment than WiFi.** EI makes this point explicitly, attributing it to the radar's directionality ([EI, MobiCom'18](https://cse.buffalo.edu/~lusu/papers/MobiCom2018.pdf)). MM-Fi's numbers above agree. The physics premise of "radar teaches CSI" is therefore supported.
3. **Cross-modal teacher→RF student is established, but the teacher is almost always a camera.** RF-Pose trained an FMCW radar student from an OpenPose teacher: AP 62.4 on visible scenes and 58.1 through walls ([CVPR'18](https://openaccess.thecvf.com/content_cvpr_2018/papers/Zhao_Through-Wall_Human_Pose_CVPR_2018_paper.pdf)). Person-in-WiFi and WiSPPN did the same for WiFi. A 2025 overview of multi-modal WiFi sensing lists only vision and RTT teachers for WiFi, and no radar teacher ([arXiv 2505.06682](https://arxiv.org/abs/2505.06682), Table 2).
4. **I found no paper that uses a cheap commercial presence radar as an online, continuous label source to adapt ESP32 CSI to new rooms.** This is the most plausible novelty. It is a negative search result, not proof of absence.
5. **Normalization may beat deep domain adaptation for cross-room ESP32 presence.** OpenCSI (ESP32-S3/C3/C6, 3 rooms) z-scores each link against its own empty-room variance. One trained threshold then transfers zero-shot, reaching binary F1 up to 0.99, where standard normalization drops to 0.87 or fails ([arXiv 2607.26665](https://arxiv.org/abs/2607.26665)).
6. **More links can hurt.** A 12-day, 9-node ESP32-C3 mesh (72 links) with day-level temporal splits found that one well-placed link beat the full mesh (AUC 0.541 vs 0.489). Both numbers are near chance under strict temporal splits, at only 1.4 Hz per link ([arXiv 2602.10823](https://arxiv.org/abs/2602.10823)). Six links at ~100 Hz is a much better regime, but fusion needs per-link gating.
7. **Generic domain adaptation recovers part of the cross-domain loss, not all of it.** On Widar3.0-G6D cross-domain HAR, DATTA raises F1 from 40.62% (baseline) to 68.13% ([arXiv 2411.13284](https://arxiv.org/abs/2411.13284)). Self-supervised pretraining plus few-shot calibration gets 83–90% on 1–3-shot gestures ([AutoFi](https://arxiv.org/abs/2205.01629)).
8. **ESP32 breathing rate is good in the lab and degrades in real homes.** With ESP32 at 120 pps against a respiration belt, RR MAE was 1.97 BrPM in older adults' homes (8 paired measurements), about 4x the lab error. HR MAE was 9.26 BPM with a +6.37 BPM bias ([Alzaabi et al., PMC12599888](https://pmc.ncbi.nlm.nih.gov/articles/PMC12599888/)). PulseFi reports BR MAE 0.09 and HR MAE 0.50 on ESP32 with only 7 seated participants ([arXiv 2510.24744](https://arxiv.org/abs/2510.24744)).
9. **Multi-person work is weak on single-antenna ESP32.** Multi-person gait identification with 1–10 people reached only 39–56% accuracy across six separation methods ([arXiv 2601.02177](https://arxiv.org/abs/2601.02177)). WiFi multi-person 3D pose exists, but needs multi-antenna NICs ([Person-in-WiFi 3D](https://openaccess.thecvf.com/content/CVPR2024/papers/Yan_Person-in-WiFi_3D_End-to-End_Multi-Person_3D_Pose_Estimation_with_Wi-Fi_CVPR_2024_paper.pdf)). People counting on ESP32 is not well established in what I could verify.
10. **AGC is now compensable on ESP32-S3.** Espressif's `esp_csi_gain_ctrl` component reads AGC and FFT gain per packet and computes a compensation factor, and it can force a fixed RX gain. Its README warns that forcing gain "may cause packet loss" ([component registry](https://components.espressif.com/components/espressif/esp_csi_gain_ctrl), [esp-csi csi_recv](https://github.com/espressif/esp-csi/blob/master/examples/get-started/csi_recv/main/app_main.c)). Log the raw gains either way.
11. **ESP32-S3 public datasets exist but are small and mostly single-link.** They include 3DO (walk/sit/lie/empty over 3 days), Wallhack1.8k, HALOC, WiFiCam, OpenCSI (S3/C3/C6 occupancy), the dilution study (C3, 312 h occupancy) and CSI-Bench (ESP32-S3 fall subset). None pairs a radar with multistatic ESP32.

---

## 1. State of the art: multi-node / multistatic CSI sensing

**Radio tomographic imaging (RTI).** Wilson & Patwari image moving people from RSS attenuation on all links of a mesh. They used 28 Crossbow TelosB nodes at 2.4 GHz around a 14 ft square ([RTI paper](https://span.ece.utah.edu/uploads/RTI.pdf)). Variance-based RTI (VRTI) tracked a person through walls with a 3.37 ft average tracking error ([arXiv 0909.5417](https://arxiv.org/abs/0909.5417)). RTI is the model-based ancestor of "6 links → zone map". With 3 nodes and 6 links you have far fewer rays than RTI's 28-node mesh. *Inference:* expect zone-level, not image-level, resolution.

**Pose and dense pose from WiFi.** All of these use multi-antenna NICs, not ESP32, and all rely on camera-derived labels.

| Work | Hardware | Result (as reported) | Split |
|---|---|---|---|
| [Person-in-WiFi](https://arxiv.org/abs/1904.00276) (ICCV'19) | 3-antenna Tx + 3-antenna Rx, 30 subcarriers @2.4 GHz | segmentation mIoU 0.66, mPCK@0.2 78.75 (OpenPose teacher 89.48) | same environments. Untrained env: mIoU 0.24, mPCK 31.06 even with GAN env-invariance |
| [WiSPPN](https://arxiv.org/abs/1904.00277) | 3-ant Tx / 3-ant Rx, camera keypoints | single-person 2D pose, 16 sites, 8 persons | — |
| [DensePose from WiFi](https://arxiv.org/abs/2301.00250) | 3 Tx + 3 Rx antennas (TP-Link AC1750-class routers) | AP 43.5 / AP@50 87.2 (image: 84.7 / 94.4) | same layout. **Unseen layout: AP 27.3** |
| [Person-in-WiFi 3D](https://openaccess.thecvf.com/content/CVPR2024/papers/Yan_Person-in-WiFi_3D_End-to-End_Multi-Person_3D_Pose_Estimation_with_Wi-Fi_CVPR_2024_paper.pdf) (CVPR'24) | 1 Tx + 3 Rx at area corners, 4 m x 3.5 m, 7 volunteers, 97k frames | 3D joint error 91.7 / 108.1 / 125.3 mm for 1/2/3 persons | in-domain |
| [MM-Fi](https://arxiv.org/abs/2305.10345) (NeurIPS D&B'23) | TP-Link N750 WiFi + TI IWR6843 mmWave + LiDAR + RGB-D, 40 subjects, 4 envs | WiFi MPJPE 186.9 / 222.3 / **367.8** mm. mmWave 109.8 / 128.4 / **166.2** mm | random / cross-subject / **cross-environment** (P1) |

**ESP32-specific multi-link and presence work.**
- **[OpenCSI](https://arxiv.org/abs/2607.26665)** (IEEE LCN 2026): an ESP32-S3/C3/C6 mesh doing binary occupancy across 3 rooms, with a same-room chip swap. Each link's z-score is computed against its own quiet-period σ. The baselines are packet-rate-bucketed (2 Hz to 60+ Hz) and time-of-day-bucketed "to absorb diurnal thermal drift". Zero-shot transfer reaches F1 up to 0.99, versus 0.87 or failure with standard normalization. The dataset is on [Zenodo 19861032](https://zenodo.org/records/19861032).
- **[Less is More / dilution effect](https://arxiv.org/abs/2602.10823)**: 9 ESP32-C3 nodes and 72 links over 12 days and 312 h, with camera ground truth and forward-chaining day-level CV. With TDMA, each link was sampled at only 1.4 Hz. Reported AUC was 0.541 for the best single link versus 0.489 for the full mesh, and random link selection matched optimized selection. The authors attribute this to links whose Fresnel zones miss the activity, which "contribute noise that overwhelms" the rest.
- **[Strohmayer & Kampel, directional antennas](https://arxiv.org/abs/2401.01388)**: ESP32-S3 at 100 Hz, through-wall HAR over 18 m across 5 rooms. NLOS accuracy was 92.0±3.5 (biquad antenna) and 86.8±4.7 (PIFA + reflector).
- **ESPectre** ([GitHub](https://github.com/francescopace/espectre)): a community single-ESP32 motion detector, recommended by the [esp-csi README](https://github.com/espressif/esp-csi). It is cited by the dilution paper as F1=98.2% for motion. That figure is not peer-reviewed and not verified.
- **Not verified** (ResearchGate preprints, full text not opened): a 3-link ESP32 device-free localization with 0.45 m median error in a 6 x 4 m lab, and a multi-zone ESP32 occupancy study reporting F1 ~0.96 (binary) and ~0.89 (3-class).

## 2. Radar or camera as teacher for WiFi (cross-modal supervision)

- **RF-Pose** ([CVPR'18](https://openaccess.thecvf.com/content_cvpr_2018/papers/Zhao_Through-Wall_Human_Pose_CVPR_2018_paper.pdf)) defines the template: "cross-modal teacher-student", with a vision teacher producing keypoint confidence maps that supervise an FMCW radar student. On visible scenes the student scored AP 62.4 against 68.8 for the teacher. Through walls the student scored AP 58.1 while the teacher fails completely. **The student can exceed the teacher's coverage.** This is the same argument as "radar teaches CSI where the radar's beam doesn't reach".
- **WiFi students with camera teachers:** [Person-in-WiFi](https://arxiv.org/abs/1904.00276) (Mask R-CNN/OpenPose annotations), [WiSPPN](https://arxiv.org/abs/1904.00277), [DensePose from WiFi](https://arxiv.org/abs/2301.00250), [Person-in-WiFi 3D](https://openaccess.thecvf.com/content/CVPR2024/papers/Yan_Person-in-WiFi_3D_End-to-End_Multi-Person_3D_Pose_Estimation_with_Wi-Fi_CVPR_2024_paper.pdf). On ESP32-S3: [WiFiCam](https://arxiv.org/abs/2401.17417) translates CSI to camera images with a multimodal VAE (data on [Zenodo 11554280](https://zenodo.org/records/11554280)).
- **Survey evidence on teachers:** [Multi-modal Wi-Fi sensing overview](https://arxiv.org/abs/2505.06682), Table 2, lists "multi-modal enhanced training" methods. Teachers there are RTT (Rizk et al.) and vision (XFall, MuAt-Va, AutoDLAR, FallDewideo, LoFi). **None uses radar.** Radar appears only in *fusion* designs, e.g., Chen et al. 2025, a radar+WiFi DANN fusion for cross-scene HAR, which needs radar at test time.
- **Multimodal-teacher distillation on datasets containing mmWave + WiFi:** [Purify-then-Align](https://arxiv.org/abs/2604.05584) distills a purified multimodal teacher into single-modality students on MM-Fi and XRF55. This is offline and dataset-level, not online room adaptation.
- **Automatic labels from another sensor:** WiADL uses WiFi-backscatter tags to pseudo-label CSI ([Springer chapter](https://link.springer.com/chapter/10.1007/978-3-031-87763-6_23), not verified). [Zhang et al.](https://arxiv.org/abs/2111.10602) apply confidence-thresholded pseudo-labeling for unlabeled target domains (mmWave and WiFi), but the pseudo-labels come from the model itself, not from radar.
- **Radar as teacher (to RF) → WiFi:** not found in the searches I ran (arXiv API title and abstract queries, plus web searches). [MM-Fi](https://arxiv.org/abs/2305.10345) explicitly lists "cross-modal supervision" as an intended use and has synchronized mmWave + WiFi, so it is the natural public testbed for a radar→WiFi distillation baseline.

## 3. Cross-environment generalization

| Approach | Representative | What it recovers (as reported) | Hardware |
|---|---|---|---|
| Domain-independent physical feature | Widar3.0 BVP ([MobiSys'19](https://dl.acm.org/doi/10.1145/3307334.3326081)) | 92.7% in-domain, 82.6–92.4% cross-domain (environment, location, orientation) without retraining. **Not verified**: from the abstract via search, PDF not opened | Intel 5300, 6 receivers. Needs multi-link Doppler, which assumes moving gestures |
| Adversarial env removal | EI ([MobiCom'18](https://cse.buffalo.edu/~lusu/papers/MobiCom2018.pdf)) | beats baselines across WiFi/ultrasound/mmWave/visible-light. Accuracy ~0.69–0.73 when target activity mix differs (Table 1) | Intel 5300, 200 pkt/s, 6 rooms |
| Adversarial + test-time adaptation | DATTA ([arXiv 2411.13284](https://arxiv.org/abs/2411.13284)) | Widar3.0-G6D cross-domain F1 40.62 → 68.13 (augmentation + DAT + TTA + weight reset). Augmentation alone: 40.62 → 49.32 | Intel 5300 data subsampled to 100 Hz, 1 antenna/Rx |
| Unsupervised DA with pseudo-labels | [Zhang et al.](https://arxiv.org/abs/2111.10602) | cross-location avg 95.65% (+15.23 points over Widar3.0), cross-environment 99.04% | Widar3.0 / radar data |
| Meta-learning, one-shot | RF-Net ([arXiv 2111.04566](https://arxiv.org/abs/2111.04566)) | outperforms baselines across WiFi/FMCW/acoustic in several envs (numbers in tables, not extracted) | Intel 5300 etc. |
| Self-supervised + few-shot | AutoFi ([arXiv 2205.01629](https://arxiv.org/abs/2205.01629)) | 83.31 / 87.46 / 89.71% gesture accuracy at 1/2/3-shot. Pretrains on *randomly captured unlabeled* CSI | Atheros APs |
| Self-supervised + adapters (counting) | [arXiv 2601.02203](https://arxiv.org/abs/2601.02203) | 10-shot crowd-count MAE 0.44 (WiFlow). Adapters within 1% of full fine-tune with 97.2% fewer params | hardware not checked |
| Unsupervised pretraining benchmark | SenseFi ([arXiv 2207.07859](https://arxiv.org/abs/2207.07859)) | CNN-5 features: 96.35% after transfer (NTU-Fi HAR→Human-ID). Deep ResNets/RNNs transfer poorly | Atheros/Intel datasets |
| Per-link normalization | OpenCSI ([arXiv 2607.26665](https://arxiv.org/abs/2607.26665)) | zero-shot binary occupancy F1 up to 0.99 across rooms and chips | ESP32-S3/C3/C6 |

**Day-to-day drift.**
- The dilution study's strict day-level splits yield near-chance AUC ([arXiv 2602.10823](https://arxiv.org/abs/2602.10823)).
- OpenCSI models diurnal thermal drift explicitly with time-of-day baselines ([arXiv 2607.26665](https://arxiv.org/abs/2607.26665)).
- The 3DO dataset (ESP32, 3 consecutive days) exists specifically to test this ([Zenodo 10925351](https://zenodo.org/records/10925351)). Its paper's findings (ICPR 2024) are not verified.
- **Not verified** (abstract snippets only): a 7-day static-environment study attributes accuracy loss to concept drift and mitigates it with noise augmentation ([IEEE 10975920](https://ieeexplore.ieee.org/document/10975920/)). "Time matters" reports only partial HAR decline one day apart, but much larger degradation for indoor positioning, which relies on static CSI components ([ScienceDirect S2542660525001489](https://www.sciencedirect.com/science/article/pii/S2542660525001489)). *Implication:* zone and localization tasks will drift faster than motion and activity tasks, which is exactly where a continuous radar teacher helps.

**What works, honestly:**
- Physics features like BVP need multi-receiver Doppler and moving targets. They do not help a stationary person.
- Adversarial and TTA methods recover roughly half the lost F1 on gestures.
- Few-shot calibration with target labels is the most reliable path, and the radar teacher supplies those labels for free.

## 4. Multi-person counting and zone occupancy

- **Counting:** DeepCount reached an average 86.4% for up to 5 people (Intel 5300 + 2-antenna router) ([arXiv 1903.05316](https://arxiv.org/abs/1903.05316)). Electronic Frog Eye (INFOCOM'14) uses a monotonic CSI-vs-crowd model ([record](https://scholar.xjtu.edu.cn/en/publications/electronic-frog-eye-counting-crowd-using-wifi/)); numbers not verified. Multi-link Doppler counting reportedly goes from 44% with 1 link to 99% with 6 links ([Tec de Monterrey record](https://research.tec.mx/vivo-tec/display/AcademicArticleSCO_85099986544)); **not verified**, though directly relevant to 6 links.
- **ESP32 multi-person ceiling:** 1–10 people, six blind-source-separation methods, 39–56% identification accuracy, 97–99% feature overlap. The authors conclude the limit is "sensing quality and spatial diversity", not the algorithm ([arXiv 2601.02177](https://arxiv.org/abs/2601.02177)). This is identification, not counting, but it bounds what single-antenna ESP32 can separate.
- **Multi-person pose** works only with multi-antenna corner receivers ([Person-in-WiFi 3D](https://openaccess.thecvf.com/content/CVPR2024/papers/Yan_Person-in-WiFi_3D_End-to-End_Multi-Person_3D_Pose_Estimation_with_Wi-Fi_CVPR_2024_paper.pdf)).
- **Zone occupancy** is best handled as per-link Fresnel-zone evidence (RTI-style). The dilution paper's physical argument applies: for a 4 m link the first Fresnel zone radius is about 0.5 m at midpoint ([arXiv 2602.10823](https://arxiv.org/abs/2602.10823)). *Inference for this room:* the bed-lamp↔desk-lamp link covers the bed/desk corridor, while the ceiling node's links slice vertically and should be the best stationary-presence links.

## 5. Breathing and heart rate from ESP32 CSI

| Study | Setup | Reference | Result (as reported) |
|---|---|---|---|
| [Alzaabi et al. 2025, older adults at home](https://pmc.ncbi.nlm.nih.gov/articles/PMC12599888/) | 2x ESP32-DevKitC-VE (PCB antenna), ESP32-CSI-Tool, 120 pps, 52 subcarriers | NUL-236 respiration belt, NUL-208 PPG | RR MAE 1.97 BrPM, ~4x the earlier lab result, PCC 0.847. HR MAE 9.26 BPM, RMSE 9.85, bias +6.37. n = 8 paired measurements, 7 volunteers |
| [Alzaabi et al., IEEE Access 2024 (lab validity)](https://doi.org/10.1109/ACCESS.2024.3349700) | ESP32, 3 m LOS, 3 x 3 m room | NUL-236 belt | Bland-Altman validity [1.29, 1.06] BPM (snippet). **Not verified**: full text not opened. Data on [IEEE DataPort](https://ieee-dataport.org/documents/respiration-rate-measurement-validity-and-repeatability-ubiquitous-non-contact-wi-fi) |
| [PulseFi](https://arxiv.org/abs/2510.24744) | ESP32, 80 Hz, HT20 64 subcarriers, seated between devices at 1–3 m, 7 participants | pulse oximeter | HR MAE 0.50 BPM (5 s window). BR MAE 0.09 (20 s window). Small n, seated, LSTM |
| [SA-WiSense](https://arxiv.org/abs/2507.17623) | ESP32, ch 11 HT40, single antenna, 5 seated targets | HKH-11Cplus respiration sensor | 91.2% detection rate up to 8.0 m. Uses cross-subcarrier CSI ratio to cancel random phase offsets on one antenna |

Context: FarSense's antenna-ratio trick, which cancels CFO, SFO and packet detection delay (PDD), needs ≥2 antennas ([arXiv 1907.03994](https://arxiv.org/abs/1907.03994)). On a single-antenna ESP32 the equivalent is the cross-subcarrier ratio ([SA-WiSense](https://arxiv.org/abs/2507.17623)).

**Realistic expectation:** RR to about ±2 BrPM in real homes when the subject is still. HR is unreliable. I found no peer-reviewed head-to-head between ESP32 CSI and a 60 GHz breathing radar such as the LD6002, so the LD6002's own accuracy also needs validation against a belt before it serves as a teacher.

## 6. Public ESP32 CSI datasets

| Dataset | Chip / setup | Labels | Format | Link |
|---|---|---|---|---|
| 3DO | ESP32 through-wall, 3 consecutive days, 42 x 5-min recordings, ~1.25 M packets | per-packet class (empty / walk / sit / lie) + 3D trajectory | `csiposreg.csv` raw packets + `.npy` complex cache | [Zenodo 10925351](https://zenodo.org/records/10925351), [loader](https://github.com/StrohmayerJ/3DO) |
| HALOC | ESP32-S3 + directional antenna, hallway | 3D position per packet | CSV, one ESP-IDF packet per row, `data` + `x,y,z` | [Zenodo 10715595](https://zenodo.org/records/10715595) |
| Wallhack1.8k | ESP32-S3 biquad / PIFA, LOS + NLOS over 18 m | activities, 1806 amplitude spectrograms | spectrograms | [paper](https://arxiv.org/abs/2401.01388), [repo](https://github.com/StrohmayerJ/wallhack1.8k) |
| WiFiCam | ESP32-S3 through-wall | paired RGB frames | `csi.csv` + `csiComplex.npy` + PNGs | [Zenodo 11554280](https://zenodo.org/records/11554280) |
| OpenCSI | ESP32-S3/C3/C6, 3 rooms, 4 x 12-min sessions | binary occupancy + calibration state | tar.gz with README/DATASHEET | [Zenodo 19861032](https://zenodo.org/records/19861032) |
| Less is More | 9x ESP32-C3, 72 links, 312 h, 12 days | occupancy (camera GT) | firmware + analysis code | [arXiv](https://arxiv.org/abs/2602.10823), [code](https://github.com/brunobastosrodrigues/less-is-more-wifi-sensing) |
| CSI-Bench (fall subset) | ESP32-S3, 1x1, 64 subcarriers @ 2.4 GHz HT20, 6 environments | falls (video-annotated) | benchmark splits | [arXiv 2505.21866](https://arxiv.org/abs/2505.21866) |
| Older-adult RR | ESP32 + ESP32-CSI-Tool | respiration belt | CSV | [IEEE DataPort](https://ieee-dataport.org/documents/respiration-rate-measurement-validity-and-repeatability-ubiquitous-non-contact-wi-fi) |
| ESP-Fi HAR (2026) | ESP32, 4 scenarios, 7 activities | activities | GitHub (per abstract) | [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1570870526000582) (not verified) |

The raw-format baselines are the Espressif `CSI_DATA,...` CSV line ([esp-csi get-started](https://github.com/espressif/esp-csi/blob/master/examples/get-started/README.md)) and the [ESP32-CSI-Tool](https://github.com/StevenMHernandez/ESP32-CSI-Tool) CSV. **Gap:** no public dataset combines a multistatic ESP32 setup with a co-located mmWave radar and camera pose. MM-Fi has radar+WiFi+pose, but on Atheros NICs.

## 7. ESP32 CSI pitfalls (Espressif primary sources)

- **CSI layout (ESP32-S3):** each subcarrier is 2 signed bytes, imaginary then real, in the order LLTF, HT-LTF, STBC-HT-LTF. Total length depends on secondary channel, HT/non-HT and STBC: e.g., 128 B for non-HT 20 MHz, 256/384 B for HT20 non-STBC/STBC, up to 612 B for HT40 STBC ([ESP-IDF Wi-Fi vendor features, CSI](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/wifi-driver/wifi-vendor-features.html)). On ESP32-S3, `first_word_invalid` marks the first 4 bytes as invalid "due to a hardware limitation". The callback runs in the Wi-Fi task, so only enqueue there.
- **Config knobs** (`wifi_csi_config_t`, [esp_wifi_types_native.h](https://github.com/espressif/esp-idf/blob/master/components/esp_wifi/include/local/esp_wifi_types_native.h)):
  - `ltf_merge_en` averages LLTF and HT-LTF for HT packets.
  - `channel_filter_en` smooths adjacent subcarriers. Disable it to keep subcarriers independent.
  - `manu_scale`/`shift`: the default is *automatic* scaling. Manual scaling fixes the shift and keeps amplitude comparable across packets.
- **HT-LTF vs LLTF:** HT20 gives 56 subcarriers (52 usable data), legacy gives 52 (48 data) ([same doc](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/wifi-driver/wifi-vendor-features.html)). HT-LTF needs an HT-rate packet. ESP-NOW's default rate is 1 Mbps ([ESP-NOW docs](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/network/esp_now.html)). Espressif's own `csi_send` therefore calls `esp_now_set_peer_rate_config` on the broadcast peer with an HT PHY mode and `WIFI_PHY_RATE_MCS0_LGI` ([csi_send](https://github.com/espressif/esp-csi/blob/master/examples/get-started/csi_send/main/app_main.c)).
- **ESP-NOW + STA:** the peer channel must equal the channel the station is on ([ESP-NOW docs](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/network/esp_now.html)), so the router's channel and channel changes become your channel. `ESP_ERR_ESPNOW_NO_MEM` in Espressif's FAQ means the channel is congested ([get-started README](https://github.com/espressif/esp-csi/blob/master/examples/get-started/README.md)). Espressif recommends a dedicated broadcast transmitter as the most accurate topology ([esp-csi README](https://github.com/espressif/esp-csi)).
- **AGC / gain:** `esp_csi_gain_ctrl` supports ESP32-S3. It ships as a precompiled `.a` with Apache-2.0 headers ([registry v0.1.5](https://components.espressif.com/components/espressif/esp_csi_gain_ctrl)). It provides:
  - `get_rx_gain(rx_ctrl)` → AGC and FFT gain per packet
  - a median baseline from recorded samples
  - `get_gain_compensation` → a float scale factor
  - `set_rx_force_gain`, documented as "may cause packet loss"; passing 0,0 restores AGC

  The reference receiver records 100 packets, takes the baseline, and multiplies CSI by the factor ([csi_recv](https://github.com/espressif/esp-csi/blob/master/examples/get-started/csi_recv/main/app_main.c)). *Inference:* forcing gain on a node that is also a router-connected STA risks the router link, so prefer compensation plus logging.
- **Phase:** single-antenna CSI phase carries CFO, SFO and packet-boundary-detection offsets ([SA-WiSense eq. 6](https://arxiv.org/abs/2507.17623), [FarSense](https://arxiv.org/abs/1907.03994)). Use amplitude, cross-subcarrier ratios, or a linear-fit phase sanitization. Raw phase is not usable.
- **Timestamps and power save:** `rx_ctrl.timestamp` is local µs and "precise only if modem sleep or light sleep is not enabled" ([types header](https://github.com/espressif/esp-idf/blob/master/components/esp_wifi/include/local/esp_wifi_types_native.h)). Station modem sleep (`WIFI_PS_MIN_MODEM`) is the default and starts on association, so call `esp_wifi_set_ps(WIFI_PS_NONE)` ([power-save docs](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/wifi-driver/wifi-performance-and-power-save.html)). With BT coexistence, Wi-Fi sleeps outside its time slice even with PS off. Each node's clock is local and there is no cross-node sync in the CSI API.
- **Packet rates seen in practice:** 100 Hz (Espressif default `CONFIG_SEND_FREQUENCY`, Strohmayer), 80 Hz (PulseFi), 120 pps (Alzaabi), 200 pps on Intel (EI). I could not find a documented maximum CSI rate for ESP32-S3 (not verified).
- **Antenna and housing:** Espressif says external IPEX antennas beat the PCB antenna, which is directional, and recommends testing with nobody present ([esp-csi README](https://github.com/espressif/esp-csi)). The get-started guide recommends >1 m between devices and calls C5/C6 the best RF chips ([README](https://github.com/espressif/esp-csi/blob/master/examples/get-started/README.md)). Moving boards into lamp housings is therefore a domain shift (antenna pattern, metal, LED driver noise).

---

## Research gap this setup could fill

**Already done:**
- Camera→RF teacher-student, for both radar (RF-Pose) and WiFi (Person-in-WiFi, DensePose, MM-Fi baselines).
- Cross-room ESP32 *binary* occupancy via normalization (OpenCSI).
- Multi-link ESP32 meshes (the dilution study, including the finding that naive fusion hurts).
- ESP32 breathing in labs and homes.
- Domain adaptation and TTA on Intel-5300 benchmarks.
- Synchronized radar+WiFi datasets (MM-Fi, XRF55), used for fusion and offline multimodal distillation.

**Plausibly novel** (no counter-example found in my searches):
1. A **low-cost commercial radar (LD2410 presence/zones, LD6002 breathing) as a continuous, online pseudo-label source** that adapts ESP32 CSI in a new room or housing without human labels. This is the "radar-teacher, cheap-student" loop.
2. **Teacher confidence and coverage modeling**: radar is directional and cheap radars have their own false positives. Learning *where the teacher is trustworthy* (its FoV and range gate) and letting the CSI student generalize beyond it is an RF-Pose-style claim, with an LD2410 in place of a camera.
3. **A multistatic, role-rotating ESP32 benchmark** (6 directional links, same packet heard by all receivers) with radar + camera-pose + scripted-protocol labels, released across bedroom → second bedroom → classroom, and dev-board → lamp-housing. No public dataset has this combination.
4. **Quantifying label efficiency:** how many radar-labeled minutes match N human-labeled minutes, and how much of the MM-Fi-style cross-environment gap that recovers.

**Honest risks:**
- Cheap radar labels are coarse: presence, a distance gate, BR. They cannot teach posture. Posture still needs the camera or scripted protocols.
- Counting on single-antenna ESP32 may hit the sensing ceiling regardless of labels.
- If OpenCSI-style normalization already gives F1 ~0.99 zero-shot for presence, the teacher's added value must be shown on harder tasks (zones, stationary vs empty, posture, counting) and on drift over days.

## Pitfalls and design implications

**Node firmware:**
1. Call `esp_wifi_set_ps(WIFI_PS_NONE)` on every node. Keep BLE off during capture, or log the coexistence state.
2. Have the transmitter send ESP-NOW broadcasts with `esp_now_set_peer_rate_config` set to an HT20 MCS0 rate, so every packet carries HT-LTF. Payload: `{tx_node_id, seq, tx_esp_timer_us, role_epoch}`. Then all receivers can align on `(tx_node_id, seq)` with no clock sync, because they heard the same packet.
3. Set CSI config explicitly:
   - LLTF + HT-LTF on, `ltf_merge_en=false` to keep the raw fields separate
   - `channel_filter_en=false`
   - `manu_scale=true` with a fixed `shift`
   - Drop the first 4 bytes when `first_word_invalid`.
4. Log per packet: rssi, noise_floor, AGC and FFT gain (via `esp_csi_gain_ctrl_get_rx_gain`), rate, sig_mode, cwb, stbc, channel, secondary channel, `rx_ctrl.timestamp`, and receiver free heap. Apply gain compensation offline from the logged values, not only on-device, and do not force gain on STA-connected nodes until tested.
5. Filter CSI by source MAC (the transmitter's) and drop router frames, or store them separately as a free extra link. Detect router channel changes and mark discontinuities.
6. For role rotation, use a fixed TDMA schedule. Make each slot long enough (e.g., ≥30 s) that breathing windows are not chopped, and record the role epoch. The dilution paper's 1.4 Hz per link is the failure mode to avoid.
7. Upload with a host receive timestamp (NTP-disciplined server) and on-device `esp_timer`, so the CSI, LD2410/LD6002 UART frames and Pi camera can be aligned to within about 10 ms. Put radar frames from the same node into the same UDP stream, stamped with the same clock.

**Recording protocol:**
1. Run an **empty-room baseline** at the start of every session and every few hours, which is OpenCSI-style per-link σ. Also log time of day and HVAC/heater state.
2. **Hold out by day and by room**, never by random windows. Report in-room, cross-day and cross-room results separately, as MM-Fi's S1/S2/S3 does.
3. **Validate the teachers first:** LD2410 presence against the camera, and LD6002 BR against a belt or the camera-derived chest motion, before using them as labels. Store teacher confidence and gate distance with every label.
4. Script stationary-person segments (sit still, lie still, sleep), since mmWave presence and CSI both struggle there. Include multi-person sessions with known counts.
5. For parents and other no-camera participants, align timed protocols with radar labels. Treat them as weak labels with explicit uncertainty.
6. Record the housing transition as its own domain: same room, same positions, dev-board vs lamp housing.

---

## References

- Wilson & Patwari, Radio Tomographic Imaging with Wireless Networks. https://span.ece.utah.edu/uploads/RTI.pdf
- Wilson & Patwari, Through-Wall Motion Tracking Using Variance-Based RTI. https://arxiv.org/abs/0909.5417
- Wang et al., Person-in-WiFi (ICCV'19). https://arxiv.org/abs/1904.00276
- Wang et al., Can WiFi Estimate Person Pose? (WiSPPN). https://arxiv.org/abs/1904.00277
- Geng et al., DensePose From WiFi. https://arxiv.org/abs/2301.00250
- Yan et al., Person-in-WiFi 3D (CVPR'24). https://openaccess.thecvf.com/content/CVPR2024/papers/Yan_Person-in-WiFi_3D_End-to-End_Multi-Person_3D_Pose_Estimation_with_Wi-Fi_CVPR_2024_paper.pdf
- Yang et al., MM-Fi. https://arxiv.org/abs/2305.10345
- Zhao et al., Through-Wall Human Pose Estimation Using Radio Signals (RF-Pose, CVPR'18). https://openaccess.thecvf.com/content_cvpr_2018/papers/Zhao_Through-Wall_Human_Pose_CVPR_2018_paper.pdf
- A Short Overview of Multi-Modal Wi-Fi Sensing. https://arxiv.org/abs/2505.06682
- Weng et al., Purify-then-Align. https://arxiv.org/abs/2604.05584
- Strohmayer et al., Through-Wall Imaging based on WiFi CSI (WiFiCam). https://arxiv.org/abs/2401.17417
- Zhang et al., Unsupervised Domain Adaptation for RF-based Gesture Recognition. https://arxiv.org/abs/2111.10602
- WiADL (backscatter pseudo-labels), not verified. https://link.springer.com/chapter/10.1007/978-3-031-87763-6_23
- Zheng et al., Widar3.0 (MobiSys'19), numbers not verified. https://dl.acm.org/doi/10.1145/3307334.3326081
- Jiang et al., EI (MobiCom'18). https://cse.buffalo.edu/~lusu/papers/MobiCom2018.pdf
- Strohmayer & Kampel, DATTA. https://arxiv.org/abs/2411.13284
- Ding et al., RF-Net (SenSys'20). https://arxiv.org/abs/2111.04566
- Yang et al., AutoFi. https://arxiv.org/abs/2205.01629
- Yang et al., SenseFi. https://arxiv.org/abs/2207.07859
- Parameter-Efficient Domain Adaption for CSI Crowd-Counting. https://arxiv.org/abs/2601.02203
- Wang et al., A Survey on Wi-Fi Sensing Generalizability (IEEE COMST). https://arxiv.org/abs/2503.08008
- Khamaisi et al., OpenCSI. https://arxiv.org/abs/2607.26665, data https://zenodo.org/records/19861032
- Khamaisi & Rodrigues, Less is More: The Dilution Effect. https://arxiv.org/abs/2602.10823
- Concept drift (7-day) study, not verified. https://ieeexplore.ieee.org/document/10975920/
- Time matters (temporal generalization), not verified. https://www.sciencedirect.com/science/article/pii/S2542660525001489
- DeepCount. https://arxiv.org/abs/1903.05316
- Electronic Frog Eye (INFOCOM'14), not verified. https://scholar.xjtu.edu.cn/en/publications/electronic-frog-eye-counting-crowd-using-wifi/
- Multi-link Doppler crowd counting, not verified. https://research.tec.mx/vivo-tec/display/AcademicArticleSCO_85099986544
- Custance et al., Why Commodity WiFi Sensors Fail at Multi-Person Gait Identification (ESP32). https://arxiv.org/abs/2601.02177
- Alzaabi et al., volunteer trials, older people (PMC). https://pmc.ncbi.nlm.nih.gov/articles/PMC12599888/
- Alzaabi et al., IEEE Access 2024 validity study, not verified. https://doi.org/10.1109/ACCESS.2024.3349700 ; data https://ieee-dataport.org/documents/respiration-rate-measurement-validity-and-repeatability-ubiquitous-non-contact-wi-fi
- PulseFi. https://arxiv.org/abs/2510.24744
- SA-WiSense. https://arxiv.org/abs/2507.17623
- Zeng et al., FarSense. https://arxiv.org/abs/1907.03994
- CSI-Bench. https://arxiv.org/abs/2505.21866
- Strohmayer & Kampel, Directional Antenna Systems (Wallhack1.8k). https://arxiv.org/abs/2401.01388
- 3DO dataset. https://zenodo.org/records/10925351 ; HALOC dataset. https://zenodo.org/records/10715595 ; WiFiCam dataset. https://zenodo.org/records/11554280
- ESP-Fi HAR dataset, not verified. https://www.sciencedirect.com/science/article/abs/pii/S1570870526000582
- Espressif esp-csi repository and examples. https://github.com/espressif/esp-csi
- Espressif esp_csi_gain_ctrl component. https://components.espressif.com/components/espressif/esp_csi_gain_ctrl
- ESP-IDF Wi-Fi CSI docs (ESP32-S3). https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/wifi-driver/wifi-vendor-features.html
- ESP-IDF Wi-Fi power save docs. https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/wifi-driver/wifi-performance-and-power-save.html
- ESP-IDF ESP-NOW docs. https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/network/esp_now.html
- ESP-IDF `esp_wifi_types_native.h`. https://github.com/espressif/esp-idf/blob/master/components/esp_wifi/include/local/esp_wifi_types_native.h
- Hernandez, ESP32-CSI-Tool. https://github.com/StevenMHernandez/ESP32-CSI-Tool
- ESPectre (community). https://github.com/francescopace/espectre
