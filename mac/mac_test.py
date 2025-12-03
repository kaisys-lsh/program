import random

class Game:
    def __init__(self):
        str = random.randint(1,5)
        dex = random.randint(1,5)
        luk = random.randint(1,5)
        self.player = {'name' : '',
                       'sex' : '',
                       'str' : str,
                       'dex' : dex,
                       'luk' : luk}
        self.chack()

    def chack(self):
        name = input("이름을 설정:")
        self.player["name"] = name
        while True:
            print("성별을 선택하세요\n1.남자 2.여자")
            sex = int(input())
            if sex == 1:
                self.player["sex"] = "남자"
                print("남자 선택 완료")
                break
            elif sex == 2:
                self.player["sex"] = "여자"
                print("여자 선택 완료")
                break
            else:
                print("재대로 선택하세요.")
                continue
        for i,j in self.player.items():
            print(f"{i} : {j}")        

if __name__ == "__main__":
    Game()