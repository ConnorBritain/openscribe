# Medication Transcription Error Analysis

- Generated: `2026-02-22T15:46:23.239599+00:00`
- Sources: `data/history/history.jsonl`, `transcript_log.txt`, `transcript_log.txt.old`
- Records scanned: `2575`
- Records with medication context: `529`
- Candidate medication terms extracted: `1720`

## Likely Mis-Transcriptions

| Observed | Suggested | Entry Count | Occurrences | Confidence | Evidence |
|---|---|---:|---:|---|---|
| `monjaro` | `mounjaro` | `8` | `14` | `high` | `take_term` |
| `welbutrin` | `wellbutrin` | `6` | `6` | `high` | `unit_of_term` |
| `lonjaro` | `mounjaro` | `3` | `5` | `medium` | `term_plus_unit` |
| `torvastatin` | `atorvastatin` | `3` | `3` | `high` | `on_term` |
| `zetbound` | `zepbound` | `3` | `3` | `medium` | `take_term` |
| `bound` | `zepbound` | `3` | `3` | `low` | `term_plus_unit` |
| `ogovi` | `wegovy` | `2` | `4` | `low` | `dose_of` |
| `manjaro` | `mounjaro` | `2` | `3` | `medium` | `term_plus_unit` |
| `amlodipineh` | `amlodipine` | `2` | `2` | `high` | `on_term` |
| `diltiazam` | `diltiazem` | `2` | `2` | `medium` | `on_term` |
| `torvistatin` | `atorvastatin` | `2` | `2` | `medium` | `term_plus_unit` |
| `lizenopril` | `lisinopril` | `2` | `2` | `medium` | `on_term` |
| `sttbound` | `zepbound` | `2` | `2` | `low` | `month_of` |
| `munjaro` | `mounjaro` | `1` | `5` | `high` | `term_plus_unit` |
| `zep-bound` | `zepbound` | `1` | `3` | `high` | `unit_of_term` |
| `carvetolol` | `carvedilol` | `1` | `2` | `medium` | `on_term` |
| `metho-carbamol` | `methocarbamol` | `1` | `1` | `high` | `on_term` |
| `metocarbamol` | `methocarbamol` | `1` | `1` | `high` | `on_term` |
| `trintelix` | `trintellix` | `1` | `1` | `high` | `on_term` |
| `terrazosin` | `terazosin` | `1` | `1` | `high` | `on_term` |
| `dexamethyphenidate` | `dexmethylphenidate` | `1` | `1` | `high` | `on_term` |
| `singular` | `singulair` | `1` | `1` | `high` | `on_term` |
| `zepibound` | `zepbound` | `1` | `1` | `high` | `unit_of_term` |
| `tenolol` | `atenolol` | `1` | `1` | `high` | `term_plus_unit` |
| `aspirin-` | `aspirin` | `1` | `1` | `high` | `on_term` |
| `glucoses` | `glucose` | `1` | `1` | `high` | `take_term` |
| `ingreza` | `ingrezza` | `1` | `1` | `high` | `on_term` |
| `empigliflozin` | `empagliflozin` | `1` | `1` | `high` | `on_term` |
| `pentoprazole` | `pantoprazole` | `1` | `1` | `medium` | `on_term` |
| `vanlafaxine` | `venlafaxine` | `1` | `1` | `medium` | `term_plus_unit` |
| `amyloidipine` | `amlodipine` | `1` | `1` | `medium` | `term_plus_unit` |
| `olmisartan` | `olmesartan` | `1` | `1` | `medium` | `term_plus_unit` |
| `losinopril` | `lisinopril` | `1` | `1` | `medium` | `on_term` |
| `lisinapril` | `lisinopril` | `1` | `1` | `medium` | `on_term` |
| `clorthaladone` | `chlorthalidone` | `1` | `1` | `medium` | `term_plus_unit` |
| `torsumide` | `torsemide` | `1` | `1` | `medium` | `unit_of_term` |
| `zipbound` | `zepbound` | `1` | `1` | `medium` | `dose_of` |
| `losartin` | `losartan` | `1` | `1` | `medium` | `term_plus_unit` |
| `pantopozole` | `pantoprazole` | `1` | `1` | `medium` | `term_plus_unit` |
| `lodipine` | `lodine` | `1` | `1` | `medium` | `term_plus_unit` |

### Example Contexts

- `monjaro` -> `mounjaro`
  - `2025-11-14T00:01:26.974160+00:00 [8539eba29e1046bfb64089092a2f8513] hip and would prefer that I prescribe it. I told that he should not Ozempic once he starts taking Monjaro. We're in problem number three, breast mass on right. was noted when he was`
  - `2025-11-15T00:17:14.603314+00:00 [317db3130fb74b7884886e925f21bc8f] is also very reassured by chest being better. , patient type 2 . He been prescribed Monjaro 2.5 milligrams, he not started it yet. He knows there was a delay in pharmacy fil`
- `welbutrin` -> `wellbutrin`
  - `2025-10-24T23:48:49.617476+00:00 [8e4a085098234df980ac7564e321e6b7] e's on board with . So after discussing this, we decided the plan will be for to go up to 300 milligrams of Welbutrin. And if he has any significant negative side effects, he'll go back`
  - `2025-10-27T19:37:47.133072+00:00 [e2651476a87345069dad92ce3c9bf41a] l. Regarding patient's multiple sclerosis, continues on rituxan every six months. 's also on Welbutrin for as well as for . And finally, takes baclofen periodically for issues.`
- `lonjaro` -> `mounjaro`
  - `2026-01-23T23:21:29.430597+00:00 [dcb8f99ded564230bb1f7b92ee991e9d] First } Type two diabetes. patient is on Lonjaro 5 mg while he has not been losing any weight. A1c has significantly improved. diet`
  - `2026-01-23T23:21:29.430597+00:00 [dcb8f99ded564230bb1f7b92ee991e9d] First } Type two diabetes. patient is on Lonjaro 5 mg while he has not been losing any weight. A1c has significantly improved. di`
- `torvastatin` -> `atorvastatin`
  - `2025-11-19T00:45:37.290072+00:00 [5d15a43a680047a1aad06773c1f83663] as asthma, patient is on Wixilla, PRN, and has been refilled. Regarding , patient is on Torvastatin. And seems to triglycerides into 300 range at last check. We're going to`
  - `2025-12-13T04:23:54.850979+00:00 [175939d8ace2427aabbe6632a8c254ce] I do think that increasing the dose to tabs would be good. I've actually sent in a higher dose of Torvastatin, so when you next pick it up from , it will actually be the 80 milligram d`
- `zetbound` -> `zepbound`
  - `2025-12-08T16:46:04.700022+00:00 [4d93121c084e4f5dab5e30acfd26657e] fic changes to plan. Regarding next issue, which is sleep apnea with a BMI over 40, he has started ZetBound, and he notes that he's already lost 10 pounds, so we are going to on this m`
  - `2026-01-06T20:32:42.017835+00:00 [e7e439f7cb574b4fbb4c9ba47c432633] This patient ZetBound 5 mg for a year with effect, but fortunately had a period of time where she stoppe`
- `bound` -> `zepbound`
  - `2025-11-14T17:42:07.195668+00:00 [12d228c8aca54ccd8b5528a3aca4fc01] ested in approach, and so we discussed risks and use of medication, and I prescribed ZEP bound 2.5 milligrams. He can start it as soon as he wants. Regarding ADHD, at point, we're`
  - `2025-11-21T19:01:07.518300+00:00 [11ef99e4f6464f8fb8a7588abfba2321] t in year, he has been following with weight loss specialist here in clinic and has been on bound. He has ended up losing more than 20% of body weight, and while he started off in`
- `ogovi` -> `wegovy`
  - `2026-02-22T03:54:58.176653+00:00 [50445c3af64848c3819beaebbbe2be34] I have sent in the 1.7 mg dose of Ogovi.`
  - `2026-02-21 19:54:58 [transcript_log.txt.old:4103] I have sent in the 1.7 mg dose of Ogovi.`
- `manjaro` -> `mounjaro`
  - `2026-01-16T00:15:20.737200+00:00 [0d33e07ccb6044fd9f5615a344bc8342] cing . So as far as issues, first issue is type 2 diabetes and being overweight. He is on Manjaro 2.5 milligrams. He's had a little bit of weight loss. A1c is very is now in goal ra`
  - `2026-01-16T00:15:20.737200+00:00 [0d33e07ccb6044fd9f5615a344bc8342] iencing . So as far as issues, first issue is type 2 diabetes and being overweight. He is on Manjaro 2.5 milligrams. He's had a little bit of weight loss. A1c is very is now in goal`
- `amlodipineh` -> `amlodipine`
  - `2026-01-24T00:03:50.516010+00:00 [32c92a422f894ed4b21325aed8b0d79e] y likely he will need at least two medications to back to , so we could consider adding on amlodipineh in the future if blood pressure is high. He is going to be checking blood pr`
  - `2026-02-13T20:11:35.777286+00:00 [fdcdded7de6e4878bb3d9c8e7b2461c8] e it, but did not any other SGLT2 Is. Uh additionally, she does have hypertension and she is on amlodipineh and I discussed she could consider uh transitioning to an ARB for protection`
- `diltiazam` -> `diltiazem`
  - `2025-11-11T20:30:55.512675+00:00 [a1228408a6a14baa8871d290333af36e] ysmal afib with state, follows with cardiology department, saw on October 30th, and is on diltiazam and apixaban. Regarding toxic multinodular goiter, status post I-131 ablation,`
  - `2025-12-09T20:04:02.445677+00:00 [ef0157260f1d4747b1efc2f05a2a55ed] . 's in outside records from of year. number 12, esophageal spasm, for patient is on Diltiazam 240. They recently picked up wrong Diltiazam, unfortunately, is difficult for`
- `torvistatin` -> `atorvastatin`
  - `2026-01-12T22:23:36.265960+00:00 [9e9a7582a05e4fb0924f5d47453b742a] o we'll just continue to them periodically. Next issue, hyperlipidemia. This patient is on a torvistatin 10 milligrams without any symptoms. This prescription was refilled today and we'll`
  - `2026-01-27T20:39:18.358993+00:00 [bd9a3fad7a23479f8200a19cb28ab09d] am if it's not done by that time uh regarding next issue hyperlipidemia this patient is on a torvistatin 20 milligrams and I did refill this today uh regarding next issue impaired fastin`
- `lizenopril` -> `lisinopril`
  - `2025-10-31T20:58:09.510819+00:00 [dfc09aac2a5d4b2d84aae3453276e9a8] cerned about it, although I did express sympathy. For next issue, hypertension, he continues on lizenopril, 30 milligrams, with normal blood pressure, so I've refilled that today. And th`
  - `2025-12-16T20:28:23.832554+00:00 [aa5b7bf343aa4e41b51e448a4874aaea] m, is on chronic lifetime anticoagulation. Regarding next issue, hypertension, continues on lizenopril and furosemide, which were both refilled today. asks if needs to furosemide`
- `sttbound` -> `zepbound`
  - `2026-02-22T03:51:39.591329+00:00 [37825e9b119d44b6b769a162f59e562c] message from prior health department below regarding your insurance will only approve one month ofsttbound at a time.`
  - `2026-02-21 19:51:39 [transcript_log.txt.old:3956] message from prior health department below regarding your insurance will only approve one month ofsttbound at a time.`
- `munjaro` -> `mounjaro`
  - `2025-12-15T22:01:44.075784+00:00 [22b2647aa1dd4a77963211778f8b715e] ulin PRN. Most recently not really needed insulin and as such we have again recently just on Munjaro 7.5 milligrams. He does note A1c today was 6.3 which is at goal. being said he do`
  - `2025-12-15T22:01:44.075784+00:00 [22b2647aa1dd4a77963211778f8b715e] not need a repeat colonoscopy. I guess next issue is type 2 diabetes mellitus. patient is on Munjaro at point. Historically been on insulin PRN. Most recently not really needed in`
- `zep-bound` -> `zepbound`
  - `2025-11-19T00:42:40.868069+00:00 [40c50fc37658416eae6e280706806244] ant to . So as far as first problem, class 3 obesity and sleep apnea, patient is now on 2.5 milligrams of Zep-bound, and not had any significant negative side effects. We will pla`
  - `2025-11-19T00:42:40.868069+00:00 [40c50fc37658416eae6e280706806244] rams of Zep-bound, and not had any significant negative side effects. We will plan to to 5 milligrams of Zep-bound in weeks and continue on dose for at least one to months. I dis`

## Recognized Medication Terms (Top)

| Term | Count |
|---|---:|
| `atorvastatin` | `56` |
| `amlodipine` | `53` |
| `metformin` | `28` |
| `rosuvastatin` | `27` |
| `adderall` | `24` |
| `gabapentin` | `22` |
| `omeprazole` | `19` |
| `sertraline` | `18` |
| `metoprolol` | `18` |
| `duloxetine` | `18` |
| `levothyroxine` | `18` |
| `aspirin` | `16` |
| `losartan` | `14` |
| `mirtazapine` | `13` |
| `trazodone` | `11` |
| `eliquis` | `11` |
| `allopurinol` | `10` |
| `fluoxetine` | `9` |
| `wellbutrin` | `9` |
| `lexapro` | `9` |
| `tamsulosin` | `8` |
| `finasteride` | `8` |
| `vyvanse` | `8` |
| `prednisone` | `8` |
| `hydrochlorothiazide` | `7` |
| `apixaban` | `7` |
| `nortriptyline` | `6` |
| `lisinopril` | `6` |
| `tadalafil` | `5` |
| `tylenol` | `5` |
| `meloxicam` | `5` |
| `furosemide` | `5` |
| `oxycodone` | `5` |
| `triple` | `5` |
| `telmisartan` | `4` |
| `naltrexone` | `4` |
| `cialis` | `4` |
| `empagliflozin` | `4` |
| `atenolol` | `4` |
| `pregabalin` | `4` |

## Unresolved Candidate Terms (Top)

| Term | Count |
|---|---:|
| `amlodipine-olmisartan` | `1` |
| `atenolol-xinopril` | `1` |

## Notes

- Inputs are already redacted; `[REDACTED_NAME]` placeholders are ignored.
- The analyzer intentionally favors precision in strong medication contexts; some real errors may be missed in free-form narrative text.
- Confidence reflects string/phonetic similarity, not semantic certainty.
