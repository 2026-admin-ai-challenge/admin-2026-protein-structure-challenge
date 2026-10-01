import pytest
from app.scoring.validator import validate,SubmissionError
from app.scoring.scorer import macro_f1,score
import pandas as pd

def test_id_alignment_and_label_strings():
    assert validate(b"id,label\nB,1.10\nA,3.40\n",["A","B"],["1.10","3.40"])==["3.40","1.10"]
@pytest.mark.parametrize("content",[b"id,label\nA,1.10\nA,3.40",b"id,label\nA,1.10",b"id,label\nA,1.10\nC,3.40",b"id,label\nA,4.20\nB,3.40",b"id,label\nA,\nB,3.40",b"id,label,extra\nA,1.10,x",b"id,label\nA,1.10,x\nB,3.40",b"id,label\nA,1.10\nB,3.40,",b"id,label\nA,1.10\nB,3.40\x00",b"\xff"])
def test_invalid_submissions(content):
    with pytest.raises(SubmissionError): validate(content,["A","B"],["1.10","3.40"])
def test_macro_f1_imbalance():
    assert macro_f1(["a","a","a","b"],["a","a","a","a"],["a","b"])==pytest.approx(3/7)
    assert macro_f1(["a","b"],["a","b"],["a","b","c"])==pytest.approx(2/3)
def test_public_private_scoring():
    frame=pd.DataFrame({"label":["a","b","a","b"],"partition":["public","public","private","private"]})
    assert score(frame,["a","b","b","a"],["a","b"])=={"public":1.0,"private":0.0}
