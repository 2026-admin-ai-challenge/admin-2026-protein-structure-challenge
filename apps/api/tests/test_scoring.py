import pytest
from app.scoring.predictions import OutputRejected,check
from app.scoring.scorer import macro_f1,score
import pandas as pd

IDS,CLASSES=["TEST_000001","TEST_000002"],["1.10","3.40"]

def test_id_alignment_and_label_strings():
    assert check(b"id,label\nTEST_000002,1.10\nTEST_000001,3.40\n",IDS,CLASSES)[0]==["3.40","1.10"]
def test_warnings_pass_with_the_ids_the_validator_accepted():
    labels,summary=check(b"\xef\xbb\xbfid,label\r\nTEST_000002 ,1.10\r\nTEST_000001,3.40\r\n",IDS,CLASSES)
    assert labels==["3.40","1.10"] and "W903" in summary and "E406" in summary
@pytest.mark.parametrize("content,code",[
    (b"id,label\nTEST_000001,1.10\nTEST_000001,3.40","E402"),(b"id,label\nTEST_000001,1.10","E401"),
    (b"id,label\nTEST_000001,1.10\nTEST_000003,3.40","E403"),(b"id,label\nTEST_000001,4.20\nTEST_000002,3.40","E502"),
    (b"id,label\nTEST_000001,\nTEST_000002,3.40","E501"),(b"id,label,extra\nTEST_000001,1.10,x\nTEST_000002,3.40,x","E203"),
    (b"id,label\nTEST_000001,1.10,x\nTEST_000002,3.40","E301"),(b"id,label\nTEST_000001,1.1\nTEST_000002,3.40","E507"),
    (b"id,label\nTEST_000001,3\nTEST_000002,3.40","E504"),(b"id,label\nTRAIN_000001,1.10\nTEST_000002,3.40","E407"),
    (b"TEST_000001,1.10\nTEST_000002,3.40","E201"),(b"id,label\nTEST_000001,1.10\nTEST_000002,3.40\x00","E106"),
    (b"\xff","E104"),(b"","E102")])
def test_invalid_submissions(content,code):
    with pytest.raises(OutputRejected) as caught: check(content,IDS,CLASSES)
    assert f"[{code}]" in str(caught.value) and not caught.value.operator_fault
def test_messages_never_echo_file_values():
    with pytest.raises(OutputRejected) as caught: check(b"id,label\nSECRET-ID,1.10\nTEST_000002,SECRET-LABEL\n",IDS,CLASSES)
    assert "SECRET" not in str(caught.value) and "(1건)" in str(caught.value)
    assert "SECRET-ID" in caught.value.detail and "SECRET-LABEL" in caught.value.detail
    assert "TEST_000001" in caught.value.detail  # missing evaluation IDs: organizer log only
def test_missing_classes_are_an_operator_fault():
    with pytest.raises(OutputRejected) as caught: check(b"id,label\nTEST_000001,1.10\nTEST_000002,3.40\n",IDS,[])
    assert caught.value.operator_fault and "[E901]" in str(caught.value)
def test_macro_f1_imbalance():
    assert macro_f1(["a","a","a","b"],["a","a","a","a"],["a","b"])==pytest.approx(3/7)
    assert macro_f1(["a","b"],["a","b"],["a","b","c"])==pytest.approx(2/3)
def test_public_private_scoring():
    frame=pd.DataFrame({"label":["a","b","a","b"],"partition":["public","public","private","private"]})
    assert score(frame,["a","b","b","a"],["a","b"])=={"public":1.0,"private":0.0}
