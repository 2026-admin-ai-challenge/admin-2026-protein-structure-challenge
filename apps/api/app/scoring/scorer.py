from sklearn.metrics import f1_score

def macro_f1(truth,predictions,classes):
    return float(f1_score(truth,predictions,labels=classes,average="macro",zero_division=0))

def score(labels,predictions,classes):
    result={}
    for partition in ["public","private"]:
        mask=labels.partition.eq(partition).to_numpy()
        result[partition]=macro_f1(labels.loc[mask,"label"].tolist(),[p for p,m in zip(predictions,mask) if m],classes)
    return result
